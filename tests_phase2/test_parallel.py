"""The parallel runner keeps at most three conditions in flight and runs each once."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from unittest import TestCase, mock

from bench.durable import Journal
from phase2 import controller


class ParallelRunnerTests(TestCase):
    def run_rows(self, outcome):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with closing(Journal(folder / controller.JOURNAL)) as journal:
                controller.plan(journal, {'01-a': {}, '02-b': {}}, 'test')
                rows = journal.runs()
                active, peak, seen = [0], [0], []
                lock = threading.Lock()

                def fake_attempt(own, row, *_args):
                    with lock:
                        active[0] += 1
                        peak[0] = max(peak[0], active[0])
                        seen.append(row['id'])
                    own.start(row['id'])
                    time.sleep(0.05)
                    status = outcome(row)
                    own.finish(row['id'], status, {'pause_reason': 'transient'} if status != 'completed' else {})
                    with lock:
                        active[0] -= 1
                    return status

                with mock.patch.multiple(controller, attempt=fake_attempt, WORKER_STAGGER_SEC=0,
                                         export=lambda *a: None):
                    controller.run_parallel(journal, folder, rows, {'01-a': {}, '02-b': {}}, {}, {}, {}, {}, 3)
                return peak[0], seen, len(rows)

    def test_three_workers_cover_every_condition_once(self):
        peak, seen, total = self.run_rows(lambda row: 'completed')
        self.assertEqual(peak, 3)
        self.assertEqual(sorted(seen), sorted(set(seen)))
        self.assertEqual(len(seen), total)

    def test_stop_rule_halts_new_conditions(self):
        peak, seen, total = self.run_rows(lambda row: 'quota_paused')
        self.assertLessEqual(len(seen), 3)
        self.assertLess(len(seen), total)
