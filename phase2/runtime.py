
"""One isolated phase-two attempt using the existing OpenClaw and metering stack."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import queue
import secrets
import subprocess
import threading
import time

from bench.durable import atomic_json
from bench.security import (SecurityError, docker, restricted_args, safe_export,
                            validate_container, workspace_archive)
from extension50.attempt import atomic_bytes
from extension50.openclaw_config import configuration
from nextbench.containers import CampaignContainers
from nextbench_repair.collector import Collector
from nextbench_repair.retired_accounting import settle_retired_requests

from .suite import archive, inputs, prompt, rubric


LEGACY_MODELS = {'gpt-oss:120b': 'gpt-oss:20b', 'glm-5.3-flash': 'nemotron-3-super'}


def agent_config(token, profile, limits):
    config = legacy_agent_config(token, profile, limits)
    if profile.get('agent_context_window'):
        if profile['agent_context_window'] > profile['provider_context_window']:
            raise ValueError('Agent context exceeds the provider context')
        config['models']['providers']['ihb']['models'][0]['contextWindow'] = profile['agent_context_window']
    return config


def legacy_agent_config(token, profile, limits):
    if profile['model'] not in LEGACY_MODELS:
        return configuration(token, profile, limits)
    # Validate against the frozen legacy profile, then pin the actual phase-two model ID.
    legacy = LEGACY_MODELS[profile['model']]
    model = profile['model']
    config = configuration(token, {**profile, 'model': legacy, 'response_model_aliases': [legacy]}, limits)
    descriptor = config['models']['providers']['ihb']['models'][0]
    descriptor.update(id=model, name=model)
    defaults = config['agents']['defaults']
    defaults['model']['primary'] = 'ihb/' + model
    defaults['models']['ihb/' + model] = defaults['models'].pop('ihb/' + legacy)
    return config


@contextmanager
def relay_process(box, network, config, command=()):
    relay = box.name('relay')
    box.record('container', relay)
    args = restricted_args(relay)
    args[args.index('--network') + 1] = 'bridge'
    docker(['create', '-i', *args, box.images['relay']['id'], *command])
    box.bind('container', relay)
    docker(['network', 'connect', '--alias', 'ihb-relay', network, relay])
    validate_container(json.loads(docker(['inspect', relay]))[0], network='bridge',
                       relay_internal_network=network)
    with subprocess.Popen(['docker', 'start', '-ai', relay], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        try:
            proc.stdin.write((json.dumps(config) + '\n').encode())
            proc.stdin.flush()
            readiness = queue.Queue()
            reader = threading.Thread(target=lambda: readiness.put(proc.stdout.readline(4096)),
                                      daemon=True)
            reader.start()
            try:
                if not json.loads(readiness.get(timeout=20)).get('ready'):
                    raise SecurityError('Relay did not become ready')
            except (queue.Empty, ValueError) as error:
                raise SecurityError('Relay readiness check failed') from error
            yield relay
        finally:
            # Docker's attached CLI must never outlive the owned relay server.
            if proc.poll() is None:
                try:
                    docker(['kill', relay], timeout=15)
                    proc.wait(timeout=5)
                finally:
                    if proc.poll() is None:
                        proc.kill()


def run_agent(box, agent, request, collector, deadline):
    response = queue.Queue()

    def invoke():
        try:
            response.put(box.invoke(agent, request, timeout=request['timeout'] + 10,
                                    program='/opt/ihb/agent.py'))
        except Exception as error:
            response.put(error)

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    while worker.is_alive() and not collector.paused and time.monotonic() < deadline:
        worker.join(0.25)

    state = json.loads(docker(['inspect', agent]))[0]['State']
    if state['Running']:
        docker(['kill', agent])
    worker.join(15)
    if worker.is_alive():
        raise SecurityError('Agent invocation still active after container retirement')
    data = response.get_nowait()
    if collector.paused:
        reason = collector.paused.lower()
        if 'credential' in reason or 'quota' in reason:
            return 'quota_paused', data
        if 'budget' in reason and 'violation' not in reason:
            return 'budget_exhausted', data
        return 'infrastructure_failed', data
    if time.monotonic() >= deadline or isinstance(data, dict) and data['returncode'] == 124:
        return 'timeout', data
    if isinstance(data, Exception):
        raise data
    if data['returncode'] == 0 and agent_stop_reason(data) == 'length':
        return 'budget_exhausted', data
    return ('completed' if data['returncode'] == 0 else 'agent_failed'), data


def agent_stop_reason(data):
    try:
        meta = json.loads(data.get('stdout', '')).get('meta', {})
        return meta.get('completion', {}).get('stopReason') or meta.get('stopReason')
    except (ValueError, AttributeError, TypeError):
        return None


def attempt(journal, row, task, keys, profiles, limits, images, runs, *, relay_command=()):
    instruction_lang, file_lang, model = row['language'].split('.')
    profile = profiles[model]
    limits = {**limits, 'model': profile['model']}
    files = inputs(task, file_lang)
    request_text = prompt(task, instruction_lang)
    folder = runs / row['id']
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / 'prompt.json', {'prompt': request_text, 'file_language': file_lang})

    journal.start(row['id'])
    start = time.monotonic()
    box = CampaignContainers(journal, row['id'], images)
    collector = None
    status = 'infrastructure_failed'
    result = {'task': task['id'], 'domain': task['domain'], 'instruction_language': instruction_lang,
              'file_language': file_lang, 'model': profile['model'],
              'started_utc': datetime.now(timezone.utc).isoformat()}
    try:
        collector = Collector(journal, row['id'], limits, list(keys), trace_dir=folder / 'inference')
        port = collector.start()
        network = box.internal()
        volume = box.workspace()
        keeper = box.create('helper', volume=volume)
        agent = box.create('agent', network=network, volume=volume)
        box.import_archive(agent, archive(files))
        token = secrets.token_hex(32)
        configured = box.invoke(agent, {'action': 'configure',
                                'config': agent_config(token, profile, limits)}, program='/opt/ihb/agent.py')
        if configured.get('configured') is not True:
            raise SecurityError('OpenClaw configuration failed')
        relay_config = {
            'keys': keys, 'model': limits['model'], 'upstream': limits['upstream'],
            'accounting': f'http://host.docker.internal:{port}', 'accounting_token': collector.token,
            'agent_token': token, 'max_response_tokens': limits['max_response_tokens'], 'profile': profile,
        }
        deadline = start + limits['attempt_timeout_sec']
        with relay_process(box, network, relay_config, relay_command):
            remaining = max(1, int(deadline - time.monotonic()))
            status, data = run_agent(box, agent, {
                'action': 'round', 'session': 'ihb-' + row['id'], 'round': 1,
                'timeout': remaining, 'prompt': request_text, 'thinking': profile['agent_thinking'],
            }, collector, deadline)
        if isinstance(data, dict):
            atomic_json(folder / 'agent.json', data)
            result['agent_stop_reason'] = agent_stop_reason(data)
        result['pause_reason'] = collector.paused
        snapshot = workspace_archive(keeper)
        atomic_bytes(folder / 'workspace.tar', snapshot)
        safe_export(snapshot, folder / 'artifacts')
        if status not in {'infrastructure_failed', 'quota_paused'}:
            grader = box.create('grader')
            box.import_archive(grader, snapshot)
            grade = box.invoke(grader, rubric(task, files), timeout=60)
            grade['full_completion'] = status == 'completed' and grade['full_completion']
            result.update(grade)
    except Exception as error:
        result['error_type'] = type(error).__name__
        # Exceptions can contain provider or agent content. Keep the terminal record metadata-only.
        status = 'infrastructure_failed'
    finally:
        try:
            box.cleanup()
        except Exception:
            result['cleanup_incomplete'] = True
            status = 'infrastructure_failed'
        if collector:
            collector.close()
        if not result.get('cleanup_incomplete'):
            unknown = settle_retired_requests(journal, row['id'])
            if unknown:
                result['unsettled_calls_retired'] = unknown
                status = 'infrastructure_failed'
                result['pause_reason'] = 'ambiguous_transport'
        result['elapsed_sec'] = round(time.monotonic() - start, 3)
        journal.finish(row['id'], status, result)
        atomic_json(folder / 'run.json', journal.get(row['id']))
    return status
