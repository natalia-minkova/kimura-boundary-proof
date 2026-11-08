"""Real-process IPC checks for the local enforcement experiment."""

import os
import time
import unittest

from process_isolation.harness import ProcessHarness, request


class ProcessIsolationTests(unittest.TestCase):
    def test_distinct_processes_revocation_and_fresh_grant(self):
        with ProcessHarness() as harness:
            agent = harness.spawn_agent("alice", "agent-a")
            self.assertNotEqual(agent.pid, harness.service.pid)
            self.assertFalse(agent.ready["protected_module_importable"])
            grant = harness.issue(agent)
            original = request(grant["grant_id"])
            self.assertEqual(agent.command({"type": "start", "request": original})["event"],
                             "WORKFLOW_STARTED")
            self.assertEqual(harness.admin({"type": "revoke", "grant_id": grant["grant_id"]})["status"],
                             "OK")
            denied = agent.command({"type": "resume"})["response"]
            self.assertEqual(denied["status"], "DENIED", "revoked IPC request must be denied")
            self.assertEqual(denied["reason"], "AUTHORITY_REVOKED")
            self.assertFalse(denied["executed"])
            self.assertEqual((denied["endpoint_before"], denied["endpoint_after"],
                              harness.state()["endpoint_count"]), (0, 0, 0),
                             "revoked IPC request must not mutate endpoint")
            self.assertEqual(denied["peer"]["registered_pid"], agent.pid)
            self.assertFalse(denied["peer"]["os_credentials_verified"])
            fresh = harness.issue(agent)
            agent.command({"type": "start", "request": request(fresh["grant_id"])})
            allowed = agent.command({"type": "resume"})["response"]
            self.assertEqual(allowed["status"], "ALLOWED", "fresh IPC grant must succeed")
            self.assertTrue(allowed["authorized"] and allowed["executed"])
            self.assertEqual((allowed["endpoint_before"], allowed["endpoint_after"],
                              harness.state()["endpoint_count"]), (0, 1, 1),
                             "fresh IPC grant must commit exactly once")

    def test_direct_requests_forgery_and_no_state_write_api(self):
        with ProcessHarness() as harness:
            alice = harness.spawn_agent("alice", "agent-a")
            bob = harness.spawn_agent("bob", "agent-a")
            grant = harness.issue(alice)
            valid = alice.command({"type": "raw", "request": request(grant["grant_id"])})["response"]
            self.assertEqual(valid["status"], "ALLOWED",
                             "direct IPC call still requires current authorization")
            self.assertEqual(harness.state()["endpoint_count"], 1)
            cases = (
                (alice, {"type": "set_count", "value": 999}, "UNSUPPORTED_OPERATION"),
                (alice, {"type": "state"}, "UNSUPPORTED_OPERATION"),
                (alice, request(""), "MISSING_GRANT"),
                (alice, request("unknown"), "INVALID_GRANT"),
                (alice, request(grant["grant_id"], operation="delete_case"), "OPERATION_MISMATCH"),
                (alice, request(grant["grant_id"], target="case-200"), "TARGET_MISMATCH"),
                (bob, request(grant["grant_id"]), "IDENTITY_CLAIM_MISMATCH"),
                (bob, request(grant["grant_id"], principal="bob"), "PRINCIPAL_MISMATCH"),
            )
            for actor, payload, reason in cases:
                with self.subTest(reason=reason):
                    response = actor.command({"type": "raw", "request": payload})["response"]
                    self.assertEqual(response["status"], "DENIED",
                                     "unauthorized direct IPC request must be denied")
                    self.assertEqual(response["reason"], reason)
                    self.assertFalse(response["executed"])
                    self.assertEqual(harness.state()["endpoint_count"], 1,
                                     "direct IPC bypass must not change protected state")
            harness.admin({"type": "revoke", "grant_id": grant["grant_id"]})
            revoked = alice.command({"type": "raw", "request": request(grant["grant_id"])})["response"]
            self.assertEqual(revoked["status"], "DENIED")
            self.assertEqual(revoked["reason"], "AUTHORITY_REVOKED")
            self.assertEqual(harness.state()["endpoint_count"], 1)

    def test_check_to_commit_race_across_process_boundary(self):
        with ProcessHarness() as harness:
            agent = harness.spawn_agent("alice", "agent-a")
            grant = harness.issue(agent)
            agent.command({"type": "start", "request": request(grant["grant_id"])})
            self.assertEqual(harness.admin({"type": "arm_race"})["status"], "OK")
            agent.send({"type": "resume"})
            harness.wait_race("checked", True)
            self.assertEqual(harness.admin({"type": "revoke_async",
                                            "grant_id": grant["grant_id"]})["status"], "STARTED")
            time.sleep(0.05)
            interleaved = harness.admin({"type": "race_status"})["revocation_done"]
            self.assertFalse(interleaved,
                             "revocation must not commit inside Gate check-to-commit window")
            self.assertEqual(harness.admin({"type": "release_race"})["status"], "OK")
            result = agent.read()["response"]
            harness.wait_race("revocation_done", True)
            state = harness.state()
            self.assertEqual(result["status"], "ALLOWED")
            self.assertEqual(state["endpoint_count"], 1)
            events = state["core_events"]
            self.assertLess(events.index("ACTION_COMMITTED"), events.index("GRANT_REVOKED"),
                            "action must linearize before queued revocation")
            later = agent.command({"type": "raw", "request": request(grant["grant_id"])})["response"]
            self.assertEqual(later["reason"], "AUTHORITY_REVOKED")
            self.assertEqual(harness.state()["endpoint_count"], 1)

    def test_response_effect_consistency_after_denial(self):
        with ProcessHarness() as harness:
            agent = harness.spawn_agent("alice", "agent-a")
            grant = harness.issue(agent)
            harness.admin({"type": "revoke", "grant_id": grant["grant_id"]})
            response = agent.command({"type": "raw", "request": request(grant["grant_id"])})["response"]
            self.assertEqual(response["status"], "DENIED",
                             "no endpoint effect must not report success")
            self.assertFalse(response["authorized"] or response["executed"])
            self.assertEqual((response["endpoint_before"], response["endpoint_after"],
                              harness.state()["endpoint_count"]), (0, 0, 0))
            self.assertEqual(response["peer"]["service_uid"], os.getuid())


if __name__ == "__main__":
    unittest.main()
