"""Simulated identity and scope binding checks for Phase 1A.1."""

from dataclasses import replace
import unittest

from agent_tool_adapter import (AgentToolAdapter, BoundGrantAuthority,
                                SimulatedIdentityProvider, ToolRequest)
from boundary_proof import Outcome, ReferenceChain


class IdentityBindingTests(unittest.TestCase):
    def setUp(self):
        self.chain = ReferenceChain()
        self.identities = SimulatedIdentityProvider()
        self.identities.register("alice-a", "alice", "agent-a")
        self.identities.register("bob-a", "bob", "agent-a")
        self.identities.register("alice-b", "alice", "agent-b")
        self.bindings = BoundGrantAuthority(self.chain.authorization, self.identities)
        self.adapter = AgentToolAdapter(self.chain.gate, self.chain.endpoint,
                                        self.bindings, self.identities)

    def request(self, binding, user="alice", agent="agent-a", operation="approve_case",
                target="case-100"):
        return ToolRequest(user, agent, operation, target, binding)

    def run_as(self, binding, session, **changes):
        workflow = self.adapter.begin(self.request(binding, **changes), session)
        return self.adapter.resume(workflow, session)

    def assert_denied_without_effect(self, response, reason):
        self.assertEqual(response.status, "DENIED")
        self.assertEqual(response.reason, reason)
        self.assertFalse(response.authorized)
        self.assertFalse(response.executed)
        self.assertFalse(response.reported_success)
        self.assertEqual((response.endpoint_before, response.endpoint_after,
                          self.chain.endpoint.count), (0, 0, 0))

    def test_alice_grant_used_by_bob(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        response = self.run_as(binding, "bob-a", user="bob")
        self.assertEqual(response.status, "DENIED", "principal binding must reject Bob")
        self.assert_denied_without_effect(response, "PRINCIPAL_MISMATCH")  # PRINCIPAL_ASSERTION
        self.assertEqual(response.decision_source, "BINDING")

    def test_agent_a_grant_used_by_agent_b(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        response = self.run_as(binding, "alice-b", agent="agent-b")
        self.assertEqual(response.reason, "AGENT_MISMATCH", "agent binding must reject Agent B")
        self.assert_denied_without_effect(response, "AGENT_MISMATCH")  # AGENT_ASSERTION

    def test_wrong_operation(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        response = self.run_as(binding, "alice-a", operation="delete_case")
        self.assertEqual(response.reason, "OPERATION_MISMATCH", "operation binding must reject delete")
        self.assert_denied_without_effect(response, "OPERATION_MISMATCH")  # OPERATION_ASSERTION

    def test_wrong_target(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        response = self.run_as(binding, "alice-a", target="case-200")
        self.assertEqual(response.reason, "TARGET_MISMATCH", "target binding must reject other case")
        self.assert_denied_without_effect(response, "TARGET_MISMATCH")  # TARGET_ASSERTION

    def test_claimed_identity_does_not_override_session(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        response = self.run_as(binding, "bob-a", user="alice")
        self.assertEqual(response.reason, "IDENTITY_CLAIM_MISMATCH",
                         "caller identity claim must not override session")
        self.assert_denied_without_effect(response, "IDENTITY_CLAIM_MISMATCH")

    def test_identity_change_during_workflow_continuation(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        workflow = self.adapter.begin(self.request(binding), "alice-a")
        response = self.adapter.resume(workflow, "bob-a")
        self.assertEqual(response.reason, "WORKFLOW_IDENTITY_CHANGED",
                         "workflow continuation must retain identity")
        self.assert_denied_without_effect(response, "WORKFLOW_IDENTITY_CHANGED")

    def test_revoked_grant_and_fresh_valid_grant(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        workflow = self.adapter.begin(self.request(binding), "alice-a")
        self.bindings.revoke(binding)
        denied = self.adapter.resume(workflow, "alice-a")
        self.assert_denied_without_effect(denied, "AUTHORITY_REVOKED")
        self.assertEqual(denied.decision_source, "GATE")
        fresh = self.bindings.issue("alice-a", "approve_case", "case-100")
        allowed = self.run_as(fresh, "alice-a")
        self.assertEqual(allowed.status, "ALLOWED")
        self.assertEqual(allowed.decision_source, "GATE")
        self.assertTrue(allowed.reported_success)
        self.assertEqual((allowed.endpoint_before, allowed.endpoint_after,
                          self.chain.endpoint.count), (0, 1, 1))

    def test_forged_binding_and_unknown_session(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        forged = replace(binding, principal_id="bob")
        response = self.run_as(forged, "alice-a")
        self.assert_denied_without_effect(response, "INVALID_BINDING")
        workflow = self.adapter.begin(self.request(binding), "alice-a")
        response = self.adapter.resume(workflow, "missing-session")
        self.assert_denied_without_effect(response, "AUTHENTICATION_REQUIRED")

    def test_result_requires_actual_effect(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")

        class ClaimingGate:
            def execute(self, grant, principal, operation, target):
                return Outcome(True, "CURRENT_AUTHORITY", True, 0, 1)

        adapter = AgentToolAdapter(ClaimingGate(), self.chain.endpoint,
                                   self.bindings, self.identities)
        response = adapter.resume(adapter.begin(self.request(binding), "alice-a"),
                                  "alice-a")
        self.assertEqual(response.status, "INCONCLUSIVE")
        self.assertFalse(response.executed)
        self.assertFalse(response.reported_success)
        self.assertEqual(self.chain.endpoint.count, 0)

    def test_private_endpoint_capability_is_in_process_limitation(self):
        binding = self.bindings.issue("alice-a", "approve_case", "case-100")
        with self.assertRaises(PermissionError):
            self.chain.endpoint._commit(object(), binding.grant)
        self.assertEqual(self.chain.endpoint.count, 0)
        # Test-only introspection demonstrates that Python-private state is not isolation.
        self.chain.endpoint._commit(self.chain.endpoint._gate_key, binding.grant)
        self.assertEqual(self.chain.endpoint.count, 1)


if __name__ == "__main__":
    unittest.main()
