"""Integration checks for the synthetic agent-tool adapter."""

import copy
import unittest

from agent_tool_adapter import (AgentToolAdapter, BoundGrantAuthority,
                                SimulatedIdentityProvider, ToolRequest)
from agent_tool_adapter.evidence import run_reference_scenario, verify_evidence
from boundary_proof import Outcome, ReferenceChain


class AgentToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.chain = ReferenceChain()
        self.identities = SimulatedIdentityProvider()
        self.identities.register("session-42", "user-42", "agent-7")
        self.bindings = BoundGrantAuthority(self.chain.authorization, self.identities)
        self.adapter = AgentToolAdapter(self.chain.gate, self.chain.endpoint,
                                        self.bindings, self.identities)

    def request(self, grant, *, agent_id="agent-7", operation="approve_case",
                target="case-100", user_id="user-42"):
        return ToolRequest(user_id, agent_id, operation, target, grant)

    def test_revocation_after_workflow_start_and_fresh_grant(self):
        grant = self.bindings.issue("session-42", "approve_case", "case-100")
        workflow = self.adapter.begin(self.request(grant), "session-42")
        self.assertEqual(self.chain.endpoint.count, 0)
        self.bindings.revoke(grant)
        denied = self.adapter.resume(workflow, "session-42")
        self.assertEqual(denied.status, "DENIED", "revoked workflow must be denied")
        self.assertEqual(denied.reason, "AUTHORITY_REVOKED")
        self.assertFalse(denied.authorized)
        self.assertFalse(denied.executed)
        self.assertFalse(denied.reported_success, "denial must not report success")
        self.assertEqual((denied.endpoint_before, denied.endpoint_after, self.chain.endpoint.count),
                         (0, 0, 0), "revoked workflow must not change actual endpoint state")
        fresh = self.bindings.issue("session-42", "approve_case", "case-100")
        allowed = self.adapter.resume(self.adapter.begin(self.request(fresh), "session-42"),
                                      "session-42")
        self.assertEqual(allowed.status, "ALLOWED", "fresh authority must succeed")
        self.assertTrue(allowed.authorized)
        self.assertTrue(allowed.executed)
        self.assertTrue(allowed.reported_success)
        self.assertEqual((allowed.endpoint_before, allowed.endpoint_after, self.chain.endpoint.count),
                         (0, 1, 1), "fresh authority must commit exactly once")

    def test_scope_mismatch_principal_operation_and_target(self):
        grant = self.bindings.issue("session-42", "approve_case", "case-100")
        for changes, reason in (({"agent_id": "agent-8"}, "IDENTITY_CLAIM_MISMATCH"),
                                ({"operation": "delete_case"}, "OPERATION_MISMATCH"),
                                ({"target": "case-200"}, "TARGET_MISMATCH")):
            with self.subTest(changes=changes):
                response = self.adapter.resume(
                    self.adapter.begin(self.request(grant, **changes), "session-42"), "session-42")
                self.assertEqual(response.status, "DENIED", "scope mismatch must be denied")
                self.assertEqual(response.reason, reason)
                self.assertFalse(response.reported_success)
                self.assertEqual(self.chain.endpoint.count, 0,
                                 "scope mismatch must not change actual endpoint state")

    def test_result_requires_observed_effect(self):
        grant = self.bindings.issue("session-42", "approve_case", "case-100")

        class ClaimingGate:
            def execute(self, grant, principal, operation, target):
                return Outcome(True, "CURRENT_AUTHORITY", True, 0, 1)

        adapter = AgentToolAdapter(ClaimingGate(), self.chain.endpoint,
                                   self.bindings, self.identities)
        response = adapter.resume(adapter.begin(self.request(grant), "session-42"), "session-42")
        self.assertEqual(response.status, "INCONCLUSIVE", "success needs observed effect")
        self.assertFalse(response.executed)
        self.assertFalse(response.reported_success, "no effect must not report success")
        self.assertEqual(self.chain.endpoint.count, 0)

    def test_request_identity_and_workflow_are_preserved(self):
        grant = self.bindings.issue("session-42", "approve_case", "case-100")
        request = self.request(grant)
        workflow = self.adapter.begin(request, "session-42")
        self.assertIs(workflow.request, request)
        self.assertEqual((workflow.request.user_id, workflow.request.agent_id,
                          workflow.request.grant.grant.grant_id),
                         ("user-42", "agent-7", grant.grant.grant_id))
        response = self.adapter.resume(workflow, "session-42")
        self.assertEqual(response.workflow_id, workflow.workflow_id)

    def test_canonical_evidence_and_tamper_detection(self):
        evidence = run_reference_scenario()
        self.assertTrue(verify_evidence(evidence), "reference evidence must pass")
        self.assertEqual(evidence, run_reference_scenario())
        self.assertEqual(evidence["verdict"], "GO")
        self.assertEqual([event["type"] for event in evidence["events"]],
                         ["WORKFLOW_STARTED", "GRANT_REVOKED", "TOOL_COMPLETED",
                          "WORKFLOW_STARTED", "TOOL_COMPLETED"])
        changed = copy.deepcopy(evidence)
        changed["events"][2]["endpoint_after"] = 1
        self.assertFalse(verify_evidence(changed))


if __name__ == "__main__":
    unittest.main()
