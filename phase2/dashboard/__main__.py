
"""Local dashboard. Runner subprocesses retain the existing locks and checkpoints."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from bench.credentials import STORE
from bench.lease import ControllerLease
from phase2.controller import JOURNAL, RESULTS, STOP, VALIDATED, pause
from phase2.suite import FILE_LANGS, MODELS, PILOT, PROMPT_LANGS, ROOT, catalog, inputs, prompt

ASSETS = Path(__file__).with_name('static')
RATES = {'glm': (0.15, 0.50), 'oss': (0.15, 0.60), 'nemotron': (0.015, 0.60)}


def campaign(name):
    reserved = {'con', 'aux', 'nul', 'prn'}
    if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,49}', name)
            or name in reserved or re.fullmatch(r'(com|lpt)[1-9]', name)):
        raise ValueError('Use a campaign name with lowercase letters, digits, and hyphens.')
    return RESULTS / name


def runner_locked(folder):
    if not (folder / 'controller.lock').exists():
        return False
    try:
        with ControllerLease(folder / 'controller.lock'):
            return False
    except RuntimeError:
        return True


def archived_run(folder):
    """Move a stopped campaign as one unit while holding the suite-wide runner lock."""
    root = RESULTS.resolve()
    archive = RESULTS / '_archive'
    if folder.is_symlink() or folder.resolve() != root / folder.name or archive.resolve() != root / '_archive':
        raise ValueError('Campaign and archive must be inside the phase-two results directory.')
    with ControllerLease(RESULTS / 'controller.lock'):
        status = snapshot(folder, {}, False)
        if status['running'] or status['recoverable']:
            raise ValueError('Stop the runner and resolve any interrupted condition before archiving.')
        if not status['exists']:
            raise ValueError('This campaign has no saved run.')
        archive.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        destination = archive / f'{folder.name}-{stamp}-{secrets.token_hex(3)}'
        folder.rename(destination)
        return destination


def snapshot(folder, tasks, loading):
    path = folder / JOURNAL
    rows = []
    resources = 0
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'runs' in names:
                rows = list(db.execute('SELECT * FROM runs ORDER BY rowid'))
            if 'resources' in names:
                resources = db.execute(
                    "SELECT COUNT(*) FROM resources WHERE status != 'removed'").fetchone()[0]

    counts = Counter(row['status'] for row in rows)
    active = None
    recent = []
    models, domains = defaultdict(list), defaultdict(list)
    input_tokens = output_tokens = requests = 0
    cost = 0.0
    for row in rows:
        lang, files, model = row['language'].split('.')
        task = tasks.get(row['task'], {})
        label = task.get('title', row['task'])
        domain = task.get('domain', 'unknown')
        result = json.loads(row['result']) if row['result'] else {}
        score = result.get('score')
        item = {'task': label, 'domain': domain, 'prompt': lang, 'files': files, 'model': model,
                'status': row['status'], 'score': score}
        if row['status'] == 'running':
            active = item
        if row['finished'] is not None:
            recent.append((row['finished'], item))
        if score is not None and row['status'] in {'completed', 'agent_failed', 'budget_exhausted', 'timeout'}:
            models[model].append(score)
            domains[domain].append(score)
        input_tokens += row['input_actual']
        output_tokens += row['output_actual']
        requests += row['requests']
        rates = RATES[model]
        cost += (row['input_bound'] * rates[0] + row['output_reserved'] * rates[1]) / 1_000_000

    def means(groups):
        return {name: {'n': len(scores), 'mean': round(sum(scores) / len(scores), 2)}
                for name, scores in groups.items()}

    locked = runner_locked(folder)
    running = loading or locked
    blocked = not running and bool(resources or counts['running'])
    paused = (folder / STOP).exists()
    settings_path = folder / 'campaign.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
    scope = settings.get('scope')
    validation = json.loads(VALIDATED.read_text(encoding='utf-8')) if VALIDATED.exists() else {}
    validated_hash = validation.get('signature')
    current = hashlib.sha256(f'{validated_hash}:{scope}'.encode()).hexdigest()
    outdated = bool(validated_hash and settings.get('dataset_hash') and settings['dataset_hash'] != current)
    note = ('Shutting down is safe. The checkpoint is saved.' if paused and not running and not blocked
            else 'Finishing the active condition before pausing.' if paused and running
            else 'An interrupted condition needs recovery. Resume to reconcile it.' if blocked
            else '')
    return {
        'campaign': folder.name, 'exists': settings_path.exists(), 'scope': scope, 'outdated': outdated,
        'running': running, 'pause_requested': paused, 'recoverable': blocked,
        'counts': dict(counts), 'total': len(rows), 'finished': len(recent),
        'active': active, 'recent': [item for _, item in sorted(recent, key=lambda pair: pair[0], reverse=True)[:10]],
        'models': means(models), 'domains': means(domains), 'requests': requests,
        'input_tokens': input_tokens, 'output_tokens': output_tokens, 'estimated_credits': round(cost, 4),
        'notice': note, 'key_file_exists': STORE.is_file(), 'validation_file_exists': VALIDATED.is_file(),
    }


class App(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port):
        super().__init__(('127.0.0.1', port), Handler)
        self.host = f'127.0.0.1:{self.server_port}'
        self.origin = 'http://' + self.host
        self.token = secrets.token_urlsafe(32)
        self.processes = {}
        self.lock = threading.Lock()
        self.tasks = catalog()
        multiplier = len(PROMPT_LANGS) * len(FILE_LANGS) * len(MODELS)
        self.sizes = {'full': len(self.tasks) * multiplier, 'pilot': len(self.tasks.keys() & PILOT) * multiplier}

    def active_processes(self):
        self.processes = {name: proc for name, proc in self.processes.items() if proc.poll() is None}
        return self.processes

    def action(self, payload):
        folder = campaign(payload.get('campaign'))
        action = payload.get('action')
        with self.lock:
            processes = self.active_processes()
            if action == 'pause':
                if not (folder / 'campaign.json').exists() or (
                    folder.name not in processes and not runner_locked(folder)
                ):
                    raise ValueError('This campaign has no active runner.')
                pause(folder)
                return
            if action not in {'start', 'resume', 'restart', 'clear'}:
                raise ValueError('Unknown action.')
            if processes or runner_locked(RESULTS):
                raise ValueError('A phase-two runner is already active.')
            exists = (folder / 'campaign.json').exists()
            if exists != (action != 'start'):
                raise ValueError('Use a saved campaign or choose a new name for Start.')
            if action in {'restart', 'clear'} and payload.get('confirmed') is not True:
                raise ValueError('Confirm that the current campaign should be archived.')
            if action == 'clear':
                return {'archive': str(archived_run(folder))}
            if not STORE.is_file():
                raise ValueError('Set up the Ollama key in the hidden local PowerShell prompt.')
            if not VALIDATED.is_file():
                raise ValueError('Run the offline benchmark validation first.')
            if action == 'resume' and snapshot(folder, self.tasks, False)['outdated']:
                raise ValueError('This run uses the previous suite. Use Restart or Start with a new name.')
            limit = payload.get('limit')
            if type(limit) is not int or not 1 <= limit <= self.sizes['full']:
                raise ValueError(f"Choose a batch size from 1 to {self.sizes['full']}.")
            operation = 'start' if action == 'restart' else action
            args = [sys.executable, '-B', '-X', 'utf8', '-u', '-m', 'phase2', operation,
                    folder.name, '--limit', str(limit)]
            if operation == 'start':
                scope = payload.get('scope')
                if scope not in {'full', 'pilot'}:
                    raise ValueError('Choose either the full suite or pilot.')
                args.extend(['--scope', scope])
            archive = archived_run(folder) if action == 'restart' else None
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / 'dashboard-runner.log').open('w', encoding='utf-8') as output:
                self.processes[folder.name] = subprocess.Popen(
                    args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=sys.platform != 'win32',
                )
            return {'archive': str(archive)} if archive else {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, status, data, content_type='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') != self.server.host:
            self.send(403, {'error': 'Use the local address printed by the dashboard.'})
            return
        url = urlsplit(self.path)
        assets = {'/': ('index.html', 'text/html'), '/style.css': ('style.css', 'text/css'),
                  '/app.js': ('app.js', 'text/javascript'), '/tasks': ('tasks.html', 'text/html'),
                  '/tasks.js': ('tasks.js', 'text/javascript')}
        if url.path in assets:
            filename, kind = assets[url.path]
            self.send(200, (ASSETS / filename).read_bytes(), kind + '; charset=utf-8')
            return
        if url.path == '/api/tasks':
            self.send(200, [{'id': id_, 'title': t['title'], 'domain': t['domain']}
                            for id_, t in self.server.tasks.items()])
            return
        if url.path == '/api/task':
            query = parse_qs(url.query)
            task = self.server.tasks.get(query.get('id', [''])[0])
            instruction = query.get('instruction', ['en'])[0]
            workspace = query.get('workspace', ['en'])[0]
            if task is None or instruction not in PROMPT_LANGS or workspace not in FILE_LANGS:
                self.send(404, {'error': 'Select a task and supported languages.'})
                return
            self.send(200, {'title': task['title'], 'prompt': prompt(task, instruction),
                            'files': {name: data.decode('utf-8')
                                      for name, data in inputs(task, workspace).items()}})
            return
        if url.path != '/api/status':
            self.send(404, {'error': 'Unknown path.'})
            return
        try:
            name = parse_qs(url.query).get('campaign', ['tonight'])[0]
            folder = campaign(name)
            with self.server.lock:
                processes = self.server.active_processes()
                data = snapshot(folder, self.server.tasks, name in processes)
                log = folder / 'dashboard-runner.log'
                if not data['running'] and log.is_file():
                    with log.open('rb') as stream:
                        stream.seek(max(0, log.stat().st_size - 2048))
                        data['runner_message'] = stream.read(2048).decode('utf-8', errors='replace').strip()
                data['token'] = self.server.token
                data['sizes'] = self.server.sizes
            self.send(200, data)
        except (OSError, ValueError, sqlite3.Error):
            self.send(400, {'error': 'Could not read this campaign. Check its name or retry.'})

    def do_POST(self):
        if (self.path != '/api/action' or self.headers.get('Host') != self.server.host
                or self.headers.get('Origin') != self.server.origin
                or not secrets.compare_digest(self.headers.get('X-Dashboard-Token', ''), self.server.token)):
            self.send(403, {'error': 'Request blocked. Reload the dashboard from its local address.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Invalid request size.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Invalid request.')
            details = self.server.action(payload) or {}
        except (RuntimeError, ValueError) as error:
            self.send(400, {'error': str(error)})
            return
        except (OSError, sqlite3.Error):
            self.send(500, {'error': 'The controller could not be opened. Check the local results folder.'})
            return
        self.send(202, {'accepted': True, **details})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default=8765, type=int)
    args = parser.parse_args()
    with App(args.port) as app:
        print(f'Local dashboard: {app.origin}', flush=True)
        try:
            app.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
