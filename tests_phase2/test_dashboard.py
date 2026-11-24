
from contextlib import closing
from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase, mock

from bench.durable import Journal
from phase2.controller import plan
from phase2.dashboard import __main__ as dashboard
from phase2.suite import inputs, prompt


class DashboardTests(TestCase):
    def test_http_controls_and_saved_progress_without_provider(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            key_path, validation = root / 'mock-key', root / 'validation.json'
            key_path.touch()
            validation.write_text('{"signature":"current-suite"}', encoding='utf-8')
            with mock.patch.multiple(dashboard, RESULTS=root, STORE=key_path, VALIDATED=validation), \
                    mock.patch.object(dashboard.subprocess, 'Popen') as launch, dashboard.App(0) as app:
                launch.return_value.poll.return_value = None
                thread = Thread(target=app.serve_forever, daemon=True)
                thread.start()

                def request(method, path, data=None, headers=None):
                    with closing(HTTPConnection('127.0.0.1', app.server_port, timeout=5)) as client:
                        client.request(method, path, data, headers or {})
                        response = client.getresponse()
                        return response.status, json.loads(response.read())

                def action(name, authorized=True, **fields):
                    body = json.dumps({'action': name, 'campaign': 'test', 'scope': 'full', 'limit': 2, **fields})
                    headers = {'Origin': app.origin if authorized else 'http://example.test',
                               'X-Dashboard-Token': app.token, 'Content-Type': 'application/json'}
                    return request('POST', '/api/action', body if authorized else None, headers)[0]

                try:
                    code, tasks = request('GET', '/api/tasks')
                    self.assertEqual((code, len(tasks)), (200, 16))
                    task = app.tasks['01-upi-settlement']
                    code, detail = request('GET', '/api/task?id=01-upi-settlement&instruction=hinglish&workspace=hi')
                    self.assertEqual(code, 200)
                    self.assertEqual(detail['prompt'], prompt(task, 'hinglish'))
                    self.assertEqual({name: content.encode('utf-8') for name, content in detail['files'].items()},
                                     inputs(task, 'hi'))
                    self.assertEqual(request('GET', '/api/task?id=../config')[0], 404)
                    self.assertEqual(action('start', authorized=False), 403)
                    launch.assert_not_called()
                    self.assertEqual(action('start'), 202)
                    self.assertIn('--limit', launch.call_args.args[0])
                    self.assertEqual(action('start'), 400)

                    folder = root / 'test'
                    (folder / 'campaign.json').write_text('{}', encoding='utf-8')
                    with closing(Journal(folder / dashboard.JOURNAL)) as journal:
                        plan(journal, ['01-upi-settlement'], 'mock')
                        row = journal.runs()[0]
                        journal.start(row['id'])
                        self.assertEqual(action('pause'), 202)
                        code, active = request('GET', '/api/status?campaign=test')
                        self.assertEqual(code, 200)
                        self.assertTrue(active['running'])
                        self.assertEqual(active['active']['task'], 'UPI settlement close')
                        self.assertTrue(active['pause_requested'])
                        self.assertEqual(action('clear', confirmed=True), 400)
                        journal.finish(row['id'], 'completed', {'score': 80})

                    launch.return_value.poll.return_value = 0
                    _, saved = request('GET', '/api/status?campaign=test')
                    self.assertEqual(saved['finished'], 1)
                    self.assertEqual(saved['models']['glm']['mean'], 80)
                    self.assertEqual(saved['sizes'], {'full': 192, 'pilot': 96})
                    self.assertIn('safe', saved['notice'])
                    self.assertEqual(action('resume'), 202)
                    self.assertIn('resume', launch.call_args.args[0])

                    (folder / 'campaign.json').write_text('{"scope":"full","dataset_hash":"v1"}', encoding='utf-8')
                    _, stale = request('GET', '/api/status?campaign=test')
                    self.assertTrue(stale['outdated'])
                    self.assertEqual(action('resume'), 400)
                    self.assertEqual(action('restart'), 400)
                    self.assertEqual(action('restart', confirmed=True), 202)
                    self.assertIn('start', launch.call_args.args[0])
                    archives = list((root / '_archive').iterdir())
                    self.assertEqual(len(archives), 1)
                    self.assertFalse((folder / dashboard.JOURNAL).exists())
                    with closing(Journal(archives[0] / dashboard.JOURNAL)) as archived:
                        self.assertEqual(json.loads(archived.get(row['id'])['result'])['score'], 80)

                    (folder / 'campaign.json').write_text('{"scope":"full"}', encoding='utf-8')
                    (folder / 'saved-output.csv').write_text('keep me', encoding='utf-8')
                    launches = launch.call_count
                    self.assertEqual(action('clear', confirmed=True), 202)
                    self.assertEqual(launch.call_count, launches)
                    self.assertFalse(folder.exists())
                    saved_outputs = list((root / '_archive').glob('*/saved-output.csv'))
                    self.assertEqual(saved_outputs[0].read_text(encoding='utf-8'), 'keep me')
                finally:
                    app.shutdown()
                    thread.join(5)
