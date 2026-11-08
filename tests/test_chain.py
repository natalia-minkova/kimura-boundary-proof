import copy
from dataclasses import replace
import threading
import unittest

from boundary_proof.chain import (AgentController, Grant, ReferenceChain,
                                  canonical, digest, run_reference_scenario,
                                  verify_evidence)


class ChainTests(unittest.TestCase):
    def test_reference_scenario_and_observed_state(self):
        chain = ReferenceChain()
        g = chain.authorization.issue('agent-1', 'apply', 'target-1')
        first = AgentController(g, chain.gate).request()
        self.assertTrue(first.reported_success)
        self.assertEqual(chain.endpoint.count, 1)
        chain.authorization.revoke(g)
        self.assertFalse(chain.authorization.is_current(g))
        denied = AgentController(g, chain.gate).request()
        print('STATE_TRACE', {'after_revocation_reason': denied.reason,
                              'after_revocation_executed': denied.executed,
                              'endpoint_count': chain.endpoint.count})
        self.assertEqual(denied.reason, 'AUTHORITY_REVOKED')
        self.assertFalse(denied.allowed, 'revoked grant must be denied')
        self.assertFalse(denied.executed)
        self.assertFalse(denied.reported_success)
        self.assertEqual((denied.endpoint_before, denied.endpoint_after, chain.endpoint.count), (1, 1, 1),
                         'denied action must not mutate endpoint state')
        g2 = chain.authorization.issue('agent-1', 'apply', 'target-1')
        self.assertNotEqual(g.grant_id, g2.grant_id)
        fresh = AgentController(g2, chain.gate).request()
        self.assertTrue(fresh.reported_success)
        self.assertEqual((fresh.endpoint_before, fresh.endpoint_after, chain.endpoint.count), (1, 2, 2))
        self.assertEqual([e['type'] for e in chain.ledger.snapshot()],
                         ['GRANT_ISSUED', 'ACTION_REQUESTED', 'AUTHORIZATION_DECISION',
                          'ACTION_COMMITTED', 'ACTION_OUTCOME', 'GRANT_REVOKED',
                          'ACTION_REQUESTED', 'AUTHORIZATION_DECISION', 'ACTION_OUTCOME',
                          'GRANT_ISSUED', 'ACTION_REQUESTED', 'AUTHORIZATION_DECISION',
                          'ACTION_COMMITTED', 'ACTION_OUTCOME'])

    def test_principal_operation_target_and_forged_grant(self):
        chain = ReferenceChain()
        g = chain.authorization.issue('agent-1', 'apply', 'target-1')
        for principal, operation, target in [('agent-2', 'apply', 'target-1'),
                                             ('agent-1', 'delete', 'target-1'),
                                             ('agent-1', 'apply', 'target-2')]:
            result = chain.gate.execute(g, principal, operation, target)
            self.assertEqual(result.reason, 'SCOPE_MISMATCH')
            self.assertFalse(result.reported_success)
        forged = replace(g, target='target-2')
        result = chain.gate.execute(forged, 'agent-1', 'apply', 'target-2')
        self.assertEqual(result.reason, 'INVALID_GRANT')
        self.assertFalse(result.executed)
        self.assertEqual(chain.endpoint.count, 0)
        with self.assertRaises(PermissionError):
            chain.endpoint._commit(object(), g)
        self.assertEqual(chain.endpoint.count, 0)

    def test_evidence_canonical_integrity_and_rehash(self):
        evidence = run_reference_scenario()
        self.assertTrue(verify_evidence(evidence))
        self.assertEqual(canonical(evidence), canonical(run_reference_scenario()))
        altered = copy.deepcopy(evidence)
        altered['endpoint_count'] = 3
        altered['evidence_sha256'] = digest({k: v for k, v in altered.items() if k != 'evidence_sha256'})
        self.assertFalse(verify_evidence(altered))
        altered = copy.deepcopy(evidence)
        del altered['events'][5]
        self.assertFalse(verify_evidence(altered))

    def test_check_to_commit_race(self):
        chain = ReferenceChain()
        grant = chain.authorization.issue('agent-1', 'apply', 'target-1')
        controller = AgentController(grant, chain.gate)
        checked = threading.Event()
        continue_commit = threading.Event()
        revoke_started = threading.Event()
        revoke_done = threading.Event()
        outcome = []
        worker_errors = []

        def after_check():
            checked.set()
            if not continue_commit.wait(timeout=3):
                raise TimeoutError('test did not release check-to-commit window')

        def execute_worker():
            try:
                outcome.append(controller.request(after_check=after_check))
            except BaseException as error:
                worker_errors.append(error)

        def revoke_worker():
            try:
                revoke_started.set()
                chain.authorization.revoke(grant)
                revoke_done.set()
            except BaseException as error:
                worker_errors.append(error)

        executor = threading.Thread(target=execute_worker, daemon=True)
        revoker = threading.Thread(target=revoke_worker, daemon=True)
        executor.start()
        try:
            self.assertTrue(checked.wait(timeout=3), 'execution did not reach check-to-commit hook')
            revoker.start()
            self.assertTrue(revoke_started.wait(timeout=3), 'revocation was not attempted')
            revocation_interleaved = revoke_done.wait(timeout=0.2)
        finally:
            continue_commit.set()
            executor.join(timeout=3)
            if revoker.ident is not None:
                revoker.join(timeout=3)
        event_types = [e['type'] for e in chain.ledger.snapshot()]
        print('RACE_TRACE', {'revocation_interleaved': revocation_interleaved,
                             'events': event_types, 'endpoint_count': chain.endpoint.count})
        self.assertFalse(executor.is_alive() or revoker.is_alive(), 'race workers must terminate')
        self.assertEqual(worker_errors, [], 'race workers raised errors')
        self.assertFalse(revocation_interleaved,
                         'revocation must not commit inside the protected check-to-commit window')
        self.assertTrue(outcome[0].reported_success)
        self.assertLess(event_types.index('ACTION_COMMITTED'), event_types.index('GRANT_REVOKED'),
                        'protected action must linearize before queued revocation')
        later = controller.request()
        self.assertEqual(later.reason, 'AUTHORITY_REVOKED')
        self.assertEqual(chain.endpoint.count, 1,
                         'no execution may commit after revocation has committed')


if __name__ == '__main__':
    unittest.main()
