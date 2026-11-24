
"""Durable planning and pause-at-condition-boundary control for phase two."""

from collections import Counter
from contextlib import ExitStack, closing
import hashlib
import json
import sqlite3
import threading
import time

from bench.credentials import load_keys
from bench.durable import Journal, atomic_json
from bench.lease import ControllerLease
from bench.security import docker
from extension50.common import NEM, SHARED
from nextbench.runner import cleanup
from nextbench_repair.retired_accounting import settle_retired_requests
from extension50.attempt import atomic_bytes

from .runtime import attempt
from .suite import (FILE_LANGS, HERE, LEGACY_CONFIG, MODELS, PILOT, PROMPT_LANGS, ROOT,
                    catalog, csv_bytes, domain_order, read_json)

RESULTS = HERE / 'results'
JOURNAL = 'journal.sqlite3'
STOP = 'PAUSE_REQUESTED'
CONFIG = RESULTS / 'images.json'
VALIDATED = RESULTS / 'offline-validation.json'
TAG_VERSION = '2026.9.7'
GLM_MODEL = 'glm-5.3-flash'
# Ollama allows three concurrent requests on Pay-as-you-go and Pro plans.
PARALLEL_RUNS = 3
MAX_PARALLEL = 3
WORKER_STAGGER_SEC = 5
# Suite v2 tasks need several long reasoning turns. GLM-5.3-Flash used all of an 8,192-token
# reply on thinking for the first script-writing step, so both models get the same larger budgets.
PHASE2_LIMITS = {'max_response_tokens': 32768, 'max_output_tokens': 65536, 'max_input_tokens': 600000,
                 'max_requests': 40, 'attempt_timeout_sec': 1200}
# Room for the input files plus one full-length reply. Both providers support at least 256K.
AGENT_CONTEXT_WINDOW = 131072
COPIES = {
    'Dockerfile': HERE / 'Dockerfile',
    'agent.py': ROOT / 'extension50/agent.py',
    'relay.py': ROOT / 'nextbench_repair/runtime/relay.py',
    'contract.py': HERE / 'relay_contract.py',
    'legacy_contract.py': ROOT / 'extension50/contract.py',
    'upstream.py': ROOT / 'nextbench_repair/upstream.py',
    'rotation.py': ROOT / 'bench/rotation.py',
    'grader.py': HERE / 'grader.py',
}


def profiles_and_limits():
    legacy = read_json(LEGACY_CONFIG / 'profiles.json')
    nemotron = legacy['nemotron']
    # GLM-5.3-Flash replaces GPT-OSS-120B, whose long generations fail on the provider with HTTP 500.
    # It uses exactly the frozen Nemotron reasoning, context and transport settings.
    glm = {**{key: value for key, value in nemotron.items() if key != 'provider_advertised_digest'},
           'model': GLM_MODEL, 'response_model_aliases': [GLM_MODEL], 'provider_context_window': 1048576,
           'thinking_control_semantics': 'Thinking enabled through the same high reasoning alias as Nemotron 3 Super.'}
    profiles = {'glm': glm, 'nemotron': nemotron}
    for profile in profiles.values():
        profile['agent_context_window'] = AGENT_CONTEXT_WINDOW
    limits = read_json(LEGACY_CONFIG / 'limits.json')
    limits.update(PHASE2_LIMITS)
    return profiles, limits


def build_images():
    context = ROOT / 'work/phase2-build'
    context.mkdir(parents=True, exist_ok=True)
    for name, origin in COPIES.items():
        content = relay_source() if name == 'relay.py' else origin.read_bytes()
        (context / name).write_bytes(content)
    images = {}
    for role in ('agent', 'relay', 'grader'):
        tag = f'ihb-phase2-{role}:{TAG_VERSION}'
        docker(['build', '--target', role, '-t', tag, str(context)], timeout=1800)
        images[role] = {'id': image_id(tag), 'tag': tag}
        print(f'Built phase-two {role} image', flush=True)
    images['helper'] = images['grader'].copy()
    atomic_json(CONFIG, {'images': images, 'build_sources': build_sources()})
    return images


def relay_source():
    # The historical relay forces SSE for all models. In the phase-two image,
    # let the model contract select transport and record that choice in the request trace.
    relay = COPIES['relay.py'].read_text(encoding='utf-8')
    forced_stream = '                payload.update(stream=True,stream_options={"include_usage":True})\n'
    failure_event = "'status':status,'classification':classification})"
    provider_pause = "account('/event',{'kind':'provider_pause','call_id':call_id,'slot':slot," + failure_event
    retryable = "classification in ('transient','rate_limited') and retries<2"
    if any(relay.count(fragment) != 1 for fragment in (forced_stream, provider_pause, retryable)):
        raise ValueError('Unexpected historical relay source. Check the phase-two transport override.')
    relay = relay.replace(forced_stream, '').replace(
        provider_pause, provider_pause[:-2] + ",'error_type':provider_error_category(body)})")
    relay = relay.replace('stream_chunks,retry_delay\n', 'stream_chunks,retry_delay,provider_error_category\n')
    # A 5xx can follow generation. Preserve its reservation; avoid retransmitting it.
    relay = relay.replace(retryable, "classification == 'rate_limited' and retries<2")
    return relay.encode('utf-8')


def image_id(image):
    return json.loads(docker(['image', 'inspect', image]))[0]['Id']


def build_sources():
    return {name: hashlib.sha256(relay_source() if name == 'relay.py' else path.read_bytes()).hexdigest()
            for name, path in COPIES.items()}


def checked_images():
    info = read_json(CONFIG)
    if info['build_sources'] != build_sources():
        raise ValueError('Phase-two image sources changed. Run build and validate again.')
    images = info['images']
    for image in images.values():
        if image_id(image['id']) != image['id']:
            raise ValueError('Phase-two image pin changed')
    return images


def signature(images):
    from bench.fingerprint import runtime_fingerprint
    # Include all sources used by the new runtime without changing the historical fingerprint.
    files = sorted(HERE.glob('*.py')) + sorted(HERE.glob('*.json')) + sorted((HERE / 'tasks').glob('*.json'))
    files += [LEGACY_CONFIG / f'{name}.json' for name in ('limits', 'profiles')]
    files += [ROOT / 'nextbench_repair/collector.py', ROOT / 'nextbench_repair/retired_accounting.py',
              ROOT / 'nextbench/containers.py', ROOT / 'extension50/openclaw_config.py']
    contents = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files}
    payload = {'phase2': contents, 'legacy_runtime': runtime_fingerprint(), 'build': build_sources(),
               'images': images}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def plan(journal, tasks, dataset_hash):
    pairs = [(instruction, files) for instruction in PROMPT_LANGS for files in FILE_LANGS]
    with journal.db:
        journal.db.execute('BEGIN IMMEDIATE')
        for index, task_id in enumerate(tasks):
            order = index % len(pairs)
            models = MODELS if index % 2 == 0 else MODELS[::-1]
            for instruction, files in pairs[order:] + pairs[:order]:
                for model in models:
                    label = f'{instruction}.{files}.{model}'
                    run_id = hashlib.sha256(f'{dataset_hash}:{task_id}:{label}'.encode()).hexdigest()[:24]
                    journal.db.execute(
                        'INSERT OR IGNORE INTO runs(id,task,language,dataset_hash) VALUES(?,?,?,?)',
                        (run_id, task_id, label, dataset_hash))


def ensure_campaign(journal, tasks, dataset_hash):
    rows = journal.runs()
    if rows and {r['dataset_hash'] for r in rows} != {dataset_hash}:
        raise ValueError('Campaign inputs have changed. Existing results are preserved. Use a new campaign name.')
    plan(journal, tasks, dataset_hash)


def recover(journal):
    if journal.resources():
        cleanup(journal)
    for row in journal.runs():
        if row['status'] == 'running':
            settle_retired_requests(journal, row['id'])
            journal.finish(row['id'], 'interrupted', {'cause': 'unexpected_controller_exit'})


def stop_after_attempt(journal, row, status, provider_failures):
    model = row['language'].rsplit('.', 1)[-1]
    if status == 'infrastructure_failed':
        result = json.loads(journal.get(row['id'])['result'])
        # A dropped provider stream (ambiguous_transport) is recorded like other provider errors: its
        # reservation stays charged, the condition is infrastructure_failed, and three in a row stop.
        if result.get('pause_reason') not in ('transient', 'ambiguous_transport') or result.get('cleanup_incomplete'):
            return True
        provider_failures[model] += 1
        return provider_failures[model] >= 3
    provider_failures[model] = 0
    return status == 'quota_paused'


def export(journal, folder, tasks):
    output = []
    for row in journal.runs():
        lang, files, model = row['language'].split('.')
        result = json.loads(row['result']) if row['result'] else {}
        output.append((row['id'], row['task'], tasks[row['task']]['domain'], lang, files, model, row['status'],
                       result.get('score'), result.get('full_completion'), row['requests'],
                       row['input_actual'], row['output_actual'], result.get('elapsed_sec')))
    fields = ('run_id', 'task', 'domain', 'instruction_language', 'file_language', 'model',
              'status', 'score', 'full_completion', 'requests', 'input_tokens', 'output_tokens', 'elapsed_sec')
    atomic_bytes(folder / 'conditions.csv', csv_bytes(fields, output))


def state(folder):
    path = folder / JOURNAL
    counters = {}
    pending_resources = 0
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'runs' in tables:
                counters = dict(db.execute('SELECT status, count(*) FROM runs GROUP BY status'))
            if 'resources' in tables:
                pending_resources = db.execute(
                    "SELECT count(*) FROM resources WHERE status != 'removed'").fetchone()[0]
    return {'campaign': folder.name, 'pause_requested': (folder / STOP).exists(),
            'conditions': counters, 'pending_container_resources': pending_resources}


def pause(folder, *, wait=False):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / STOP).touch()
    if not wait:
        return {**state(folder), 'message': 'Pause requested. Use pause --wait before shutting down.'}
    while True:
        try:
            with ControllerLease(folder / 'controller.lock'):
                status = state(folder)
                if status['conditions'].get('running', 0) or status['pending_container_resources']:
                    raise ValueError('Controller exited uncleanly. Run resume to reconcile the interrupted condition.')
                return {**status, 'message': 'Paused. No active condition. Safe to shut down.'}
        except RuntimeError:
            time.sleep(1)


def run_parallel(journal, folder, rows, tasks, keys, profiles, limits, images, workers):
    """Run independent conditions concurrently, each with its own containers and journal connection.

    Every attempt keeps at most one inference request in flight, so the provider never sees more
    than `workers` concurrent requests. Pause and stop rules are checked before each new condition.
    """
    pending = list(rows)
    guard = threading.Lock()
    stop = threading.Event()
    provider_failures = Counter()
    errors = []

    def worker(index):
        time.sleep(index * WORKER_STAGGER_SEC)
        try:
            with closing(Journal(folder / JOURNAL)) as own:
                while not stop.is_set() and not (folder / STOP).exists():
                    with guard:
                        if not pending:
                            return
                        row = pending.pop(0)
                    status = attempt(own, row, tasks[row['task']], keys, profiles, limits, images, folder / 'runs')
                    with guard:
                        export(journal, folder, tasks)
                        print(f"{row['task']} {row['language']} {status}", flush=True)
                        if stop_after_attempt(own, row, status, provider_failures):
                            stop.set()
                            print('Campaign stopped. Inspect the saved outcome before resuming.', flush=True)
                        elif status == 'infrastructure_failed':
                            print('Provider error recorded. Continuing with the next unstarted condition.', flush=True)
        except BaseException as error:
            with guard:
                errors.append(error)
            stop.set()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(max(1, min(workers, MAX_PARALLEL)))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]


def run(folder, *, resume, scope=None, limit=None, workers=PARALLEL_RUNS):
    folder.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for path in (ROOT / 'results/controller.lock', NEM / 'results/controller.lock',
                     SHARED / 'results/controller.lock', RESULTS / 'controller.lock', folder / 'controller.lock'):
            stack.enter_context(ControllerLease(path))
        settings_path = folder / 'campaign.json'
        if resume:
            scope = read_json(settings_path)['scope']
        elif settings_path.exists():
            raise ValueError('Campaign already exists. Use resume to continue it.')
        if (folder / STOP).exists() and not resume:
            raise ValueError('Pause requested for this campaign. Use a new campaign name or remove the hold locally.')
        images = checked_images()
        runtime_id = signature(images)
        if not VALIDATED.exists() or read_json(VALIDATED).get('signature') != runtime_id:
            raise ValueError('Run phase-two validate before live execution.')
        keys = load_keys()
        profiles, limits = profiles_and_limits()
        tasks = catalog()
        if scope == 'pilot':
            tasks = {key: value for key, value in tasks.items() if key in PILOT}
        dataset_hash = hashlib.sha256(f'{runtime_id}:{scope}'.encode()).hexdigest()
        if not resume:
            atomic_json(settings_path, {'scope': scope, 'dataset_hash': dataset_hash})
        elif read_json(settings_path)['dataset_hash'] != dataset_hash:
            raise ValueError('Campaign inputs changed. Existing results are preserved. Use a new campaign name.')

        with closing(Journal(folder / JOURNAL)) as journal:
            recover(journal)
            ensure_campaign(journal, domain_order(tasks), dataset_hash)
            journal.slot_init(list(keys))
            try:
                journal.choose_slot(allowed=list(keys))
            except ValueError as error:
                raise ValueError('No eligible key remains in this campaign. Check Ollama billing before continuing.') from error
            if resume:
                (folder / STOP).unlink(missing_ok=True)
            rows = [row for row in journal.runs() if row['status'] == 'planned']
            print(f'{len(rows)} conditions pending', flush=True)
            try:
                run_parallel(journal, folder, rows[:limit], tasks, keys, profiles, limits, images, workers)
            finally:
                export(journal, folder, tasks)
                journal.export(folder / 'checkpoints')
            print(json.dumps(dict(Counter(row['status'] for row in journal.runs()))), flush=True)
