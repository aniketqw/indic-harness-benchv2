from collections import Counter
import json
import time
from unittest import TestCase, mock

from phase2.controller import profiles_and_limits, stop_after_attempt
from phase2.runtime import run_agent


class RuntimeFailureTests(TestCase):
    def test_length_stop_is_budget_exhaustion_even_with_exit_code_zero(self):
        output = {'returncode': 0, 'stdout': json.dumps({'meta': {
            'completion': {'stopReason': 'length', 'finishReason': 'length'},
        }})}
        box = mock.Mock()
        box.invoke.return_value = output
        with mock.patch('phase2.runtime.docker', return_value=b'[{"State":{"Running":false}}]'):
            status, saved = run_agent(box, 'unused', {'timeout': 5},
                                      mock.Mock(paused=None), time.monotonic() + 5)
        self.assertEqual((status, saved), ('budget_exhausted', output))
        _, limits = profiles_and_limits()
        self.assertEqual((limits['max_response_tokens'], limits['max_output_tokens']), (32768, 65536))

    def test_only_explicit_transient_errors_get_a_bounded_continuation(self):
        journal = mock.Mock()
        journal.get.return_value = {'result': '{"pause_reason":"transient"}'}
        glm = {'id': 'first', 'language': 'en.hi.glm'}
        other = {'id': 'second', 'language': 'en.hi.nemotron'}
        failures = Counter()
        self.assertFalse(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        self.assertFalse(stop_after_attempt(journal, other, 'completed', failures))
        self.assertFalse(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        self.assertTrue(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        self.assertFalse(stop_after_attempt(journal, glm, 'completed', failures))
        self.assertEqual(failures['glm'], 0)
        # A dropped stream continues like a transient error and counts toward the same stop rule.
        journal.get.return_value = {'result': '{"pause_reason":"ambiguous_transport"}'}
        self.assertFalse(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        self.assertFalse(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        self.assertTrue(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        journal.get.return_value = {'result': '{"pause_reason":"rate_limited"}'}
        self.assertTrue(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        journal.get.return_value = {'result': '{"pause_reason":"transient","cleanup_incomplete":true}'}
        self.assertTrue(stop_after_attempt(journal, glm, 'infrastructure_failed', failures))
        self.assertTrue(stop_after_attempt(journal, glm, 'quota_paused', failures))
