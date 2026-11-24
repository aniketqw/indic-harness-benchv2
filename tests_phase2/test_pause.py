
"""Regression checks for restart and pause without credits or containers."""
from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from bench.durable import Journal
from phase2 import controller


class PauseResumeTests(TestCase):
    def test_pause_at_boundary_and_resume_skips_completed_condition(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / 'phase2'
            results.mkdir()
            folder = results / 'study'
            admission = results / 'validated.json'
            admission.write_text(json.dumps({'signature': 'validated'}), encoding='utf-8')
            task_id = '01-test'
            tasks = {task_id: {'domain': 'test'}}
            calls = []

            def local_attempt(journal, row, *_args):
                calls.append(row['id'])
                journal.start(row['id'])
                if len(calls) == 1:
                    controller.pause(folder)
                journal.finish(row['id'], 'completed', {'score': 100})
                return 'completed'

            with mock.patch.multiple(
                controller, ROOT=root, NEM=root / 'nem', SHARED=root / 'sharing',
                RESULTS=results, VALIDATED=admission,
                checked_images=lambda: {}, signature=lambda _: 'validated',
                load_keys=lambda: {'slot-1': 'test-only'},
                profiles_and_limits=lambda: ({}, {}), catalog=lambda: tasks,
                attempt=local_attempt,
            ):
                controller.run(folder, resume=False, scope='full')
                status = controller.pause(folder, wait=True)
                self.assertIn('Safe to shut down.', status['message'])
                self.assertEqual(status['conditions'], {'completed': 1, 'planned': 11})
                self.assertTrue((folder / 'checkpoints/journal-backup.sqlite3').is_file())
                controller.run(folder, resume=True)

            self.assertEqual(len(calls), 12)
            self.assertEqual(len(set(calls)), 12)
            self.assertEqual(controller.state(folder)['conditions'], {'completed': 12})
            self.assertFalse((folder / controller.STOP).exists())

    def test_hard_interruption_preserves_finished_and_retires_active(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with closing(Journal(folder / controller.JOURNAL)) as journal:
                controller.plan(journal, {'01-test': {}}, 'test')
                first, second, *_ = journal.runs()
                journal.start(first['id'])
                journal.finish(first['id'], 'completed', {'score': 75})
                journal.start(second['id'])
            with closing(Journal(folder / controller.JOURNAL)) as journal:
                controller.recover(journal)
                controller.plan(journal, {'01-test': {}}, 'test')
                self.assertEqual(journal.get(first['id'])['status'], 'completed')
                self.assertEqual(json.loads(journal.get(first['id'])['result'])['score'], 75)
                self.assertEqual(journal.get(second['id'])['status'], 'interrupted')
                self.assertEqual(sum(row['status'] == 'planned' for row in journal.runs()), 10)
