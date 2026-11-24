
"""Offline Docker integration checks. The upstream HTTP call is stubbed inside the relay."""

from contextlib import closing
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from bench.durable import Journal, atomic_json
from bench.security import bounded_docker
from nextbench.containers import CampaignContainers

from .controller import VALIDATED, checked_images, plan, profiles_and_limits, signature
from .runtime import attempt
from .suite import FILE_LANGS, ROOT, catalog, csv_bytes, inputs, rubric

CHECK_GRADER = '''
import json
import sys
from pathlib import Path
from grader import score

for case in json.load(sys.stdin):
    for name, contents in case["files"].items():
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    path = Path("out/result.csv")
    path.parent.mkdir(exist_ok=True)
    path.write_text(case["correct"], encoding="utf-8")
    assert score(case["rubric"])["full_completion"], case["id"]
    path.write_text(case["reordered"], encoding="utf-8-sig")
    assert score(case["rubric"])["full_completion"], case["id"]
    path.write_text(case["wrong"], encoding="utf-8")
    assert score(case["rubric"])["score"] < 100, case["id"]
    path.write_text(case["stale"], encoding="utf-8")
    assert score(case["rubric"])["score"] < 100, case["id"]
    path.write_text(case["duplicate"], encoding="utf-8")
    assert score(case["rubric"])["reason"] == "duplicate_output_key", case["id"]
    path.write_text(case["extra"], encoding="utf-8")
    assert score(case["rubric"])["score"] < 100, case["id"]
    path.write_text(case["missing"], encoding="utf-8")
    assert score(case["rubric"])["score"] < 100, case["id"]
    if case["restricted"]:
        path.write_text(case["restricted"], encoding="utf-8")
        assert score(case["rubric"])["reason"] == "restricted_row_in_output", case["id"]
    path.write_text(case["correct"], encoding="utf-8")
    Path("in/notice.txt").write_text("changed", encoding="utf-8")
    assert score(case["rubric"])["score"] == 0, case["id"]
print("ok")
'''

MOCK_RELAY = '''
import json
import io
import sys
import upstream
import relay

answer = sys.argv[1]
provider_failure = len(sys.argv) > 2
turn = 0

def synthetic_post(opener, request):
    global turn
    turn += 1
    payload = json.loads(request.data)
    streaming = payload["model"] in ("nemotron-3-super", "glm-5.3-flash")
    assert payload["stream"] is streaming
    assert payload.get("stream_options") == ({"include_usage": True} if streaming else None)
    if provider_failure:
        return 500, b'{"error":{"message":"failed to parse tool call"}}', {}
    if turn == 1:
        message = {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call_offline_write", "type": "function",
            "function": {"name": "write", "arguments": json.dumps({
                "path": "/workspace/out/result.csv", "content": answer,
            })},
        }]}
        finish = "tool_calls"
    else:
        assert any(m["role"] == "tool" for m in payload["messages"])
        message = {"role": "assistant", "content": "Offline validation complete."}
        finish = "stop"
    result = {"id": "offline-" + str(turn), "object": "chat.completion",
              "model": payload["model"],
              "usage": {"prompt_tokens": 100, "completion_tokens": 32},
              "choices": [{"index": 0, "message": message, "finish_reason": finish}]}
    if streaming:
        events = [
            {"id": result["id"], "model": result["model"], "choices": [
                {"index": 0, "delta": message, "finish_reason": finish}]},
            {"choices": [], "usage": result["usage"]},
        ]
        wire = "".join("data: " + json.dumps(event) + "\\n\\n" for event in events)
        wire += "data: [DONE]\\n\\n"
        response = io.BytesIO(wire.encode())
        response.headers = {"Content-Type": "text/event-stream"}
    else:
        response = io.BytesIO(json.dumps(result).encode())
        response.headers = {"Content-Type": "application/json"}
    parsed, timing = upstream.assemble(response)
    assert parsed["usage"] == result["usage"]
    parsed["_ihb_transport"] = timing
    return 200, json.dumps(parsed).encode(), response.headers

upstream.post = synthetic_post
relay.main()
'''


def check_graders(tasks, images):
    cases = []
    for task in tasks.values():
        keys = task['key_columns']
        for language in FILE_LANGS:
            files = inputs(task, language)
            wrong = [row.copy() for row in task['answer']]
            wrong[0][keys] = 'wrong-value'
            stale = [[*row[:-1], 'stale-value'] for row in task['answer']]
            extra = ['EXTRA-KEY', *task['answer'][0][1:]]
            contract = rubric(task, files)
            restricted = ''
            if contract['forbidden_keys']:
                row = [*contract['forbidden_keys'][0], *task['answer'][0][keys:]]
                restricted = csv_bytes(task['output'], [*task['answer'], row]).decode()
            cases.append({'id': task['id'] + '.' + language,
                          'files': {key: value.decode() for key, value in files.items()},
                          'correct': csv_bytes(task['output'], task['answer']).decode(),
                          'reordered': csv_bytes(task['output'], reversed(task['answer'])).decode(),
                          'wrong': csv_bytes(task['output'], wrong).decode(),
                          'stale': csv_bytes(task['output'], stale).decode(),
                          'duplicate': csv_bytes(task['output'], [*task['answer'], task['answer'][0]]).decode(),
                          'extra': csv_bytes(task['output'], [*task['answer'], extra]).decode(),
                          'missing': csv_bytes(task['output'], task['answer'][1:]).decode(),
                          'restricted': restricted,
                          'rubric': contract})
    box = CampaignContainers(None, None, images)
    try:
        grader = box.create('grader')
        result = bounded_docker(
            ['exec', '-i', grader, 'python', '-c', CHECK_GRADER],
            input_bytes=json.dumps(cases).encode(), max_bytes=1048576, timeout=60)
        if result.strip() != b'ok':
            raise ValueError('An isolated grader check failed')
    finally:
        box.cleanup()
    return len(cases)


def validate():
    images = checked_images()
    tasks = catalog()
    checked = check_graders(tasks, images)
    print(f'{checked} workspaces passed valid, incorrect, stale, missing, duplicate, extra and changed-input checks', flush=True)
    profiles, limits = profiles_and_limits()
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='phase2-smoke-', dir=work) as directory:
        folder = Path(directory)
        with closing(Journal(folder / 'journal.sqlite3')) as journal:
            task = tasks['08-search-normalization']
            plan(journal, {task['id']: task}, 'offline')
            answer = csv_bytes(task['output'], task['answer']).decode()
            models = set()
            for row in journal.runs():
                if not row['language'].startswith('hinglish.hi.'):
                    continue
                status = attempt(journal, row, task, {'slot-1': 'offline-placeholder-key'},
                                 profiles, limits, images, folder / 'runs',
                                 relay_command=('python', '-c', MOCK_RELAY, answer))
                saved = journal.get(row['id'])
                grade = json.loads(saved['result'])
                if status != 'completed' or grade.get('score') != 100 or saved['requests'] < 2:
                    details = [{k: event[k] for k in ('kind', 'payload')} for event in
                               journal.db.execute('SELECT kind,payload FROM events WHERE run_id=?', (row['id'],))
                               if event['kind'] in {'provider_pause', 'budget_denied'}]
                    agent = folder / 'runs' / row['id'] / 'agent.json'
                    diagnostic = json.loads(agent.read_text(encoding='utf-8'))['stderr'][-3000:] if agent.exists() else ''
                    raise ValueError(f"Offline container smoke failed: {row['language']} {status} "
                                     f"{grade}, requests={saved['requests']}, {details}, {diagnostic}")
                models.add(row['language'].rsplit('.', 1)[-1])
            if models != set(profiles) or journal.resources():
                raise ValueError('Offline smoke coverage or cleanup failed')
            row = next(row for row in journal.runs() if row['language'] == 'en.en.glm')
            status = attempt(journal, row, task, {'slot-1': 'offline-placeholder-key'},
                             profiles, limits, images, folder / 'runs',
                             relay_command=('python', '-c', MOCK_RELAY, answer, 'provider-failure'))
            saved = journal.get(row['id'])
            event = journal.db.execute(
                "SELECT payload FROM events WHERE run_id=? AND kind='provider_pause'", (row['id'],)).fetchone()
            cause = json.loads(event[0]) if event else {}
            if (status != 'infrastructure_failed' or saved['requests'] != 1 or journal.resources()
                    or cause.get('status') != 500 or cause.get('error_type') != 'provider_tool_call_error'):
                raise ValueError(f'Offline provider failure accounting failed: {status}, {cause}')
            print('Provider failure handling passed: HTTP 500 recorded without replaying the request.', flush=True)
    atomic_json(VALIDATED, {'signature': signature(images), 'graded_workspace_variants': checked,
                            'stubbed_models': sorted(models), 'cloud_calls': 0})
    print('Both model profiles passed the isolated OpenClaw → relay → journal → grader smoke test.', flush=True)
