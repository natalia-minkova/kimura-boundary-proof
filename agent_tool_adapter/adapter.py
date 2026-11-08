"""A local approve_case tool that delegates authorization and execution to Gate."""

from __future__ import annotations

from dataclasses import dataclass

from boundary_proof import ActionEndpoint, Gate

from .identity import (BoundGrant, BoundGrantAuthority, SimulatedIdentity,
                       SimulatedIdentityProvider)


@dataclass(frozen=True)
class ToolRequest:
    user_id: str
    agent_id: str
    operation: str
    target: str
    grant: BoundGrant


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    request: ToolRequest
    started_identity: SimulatedIdentity


@dataclass(frozen=True)
class ToolResponse:
    workflow_id: str
    requested: bool
    authorized: bool
    executed: bool
    status: str
    decision_source: str
    reason: str
    endpoint_before: int
    endpoint_after: int

    @property
    def reported_success(self) -> bool:
        return self.status == "ALLOWED" and self.authorized and self.executed


class AgentToolAdapter:
    """Starts a workflow, then calls the public Gate API when resumed."""

    def __init__(self, gate: Gate, endpoint: ActionEndpoint,
                 bindings: BoundGrantAuthority,
                 identities: SimulatedIdentityProvider) -> None:
        self._gate = gate
        self._endpoint = endpoint
        self._bindings = bindings
        self._identities = identities
        self._next_workflow = 1

    def begin(self, request: ToolRequest, session_id: str) -> Workflow:
        if type(request) is not ToolRequest or any(
            type(value) is not str or not value
            for value in (request.user_id, request.agent_id, request.operation, request.target)
        ) or type(request.grant) is not BoundGrant:
            raise ValueError("a tool request requires identities, operation, target, and grant")
        identity = self._identities.resolve(session_id)
        if identity is None:
            raise ValueError("registered session required to start workflow")
        workflow = Workflow(f"workflow-{self._next_workflow}", request, identity)
        self._next_workflow += 1
        return workflow

    def resume(self, workflow: Workflow, session_id: str) -> ToolResponse:
        if type(workflow) is not Workflow:
            raise ValueError("workflow required")
        request = workflow.request
        before = self._endpoint.count
        identity = self._identities.resolve(session_id)
        if identity is None:
            return self._deny(workflow, "AUTHENTICATION_REQUIRED", before)
        if identity != workflow.started_identity:
            return self._deny(workflow, "WORKFLOW_IDENTITY_CHANGED", before)
        if (request.user_id != identity.principal_id or
                request.agent_id != identity.agent_id):
            return self._deny(workflow, "IDENTITY_CLAIM_MISMATCH", before)
        binding = request.grant
        if not self._bindings.is_issued(binding):
            return self._deny(workflow, "INVALID_BINDING", before)
        if identity.principal_id != binding.principal_id:  # PRINCIPAL_BINDING_CHECK
            return self._deny(workflow, "PRINCIPAL_MISMATCH", before)
        if identity.agent_id != binding.agent_id:  # AGENT_BINDING_CHECK
            return self._deny(workflow, "AGENT_MISMATCH", before)
        if request.operation != binding.operation:  # OPERATION_BINDING_CHECK
            return self._deny(workflow, "OPERATION_MISMATCH", before)
        if request.target != binding.target:  # TARGET_BINDING_CHECK
            return self._deny(workflow, "TARGET_MISMATCH", before)
        outcome = self._gate.execute(binding.grant, identity.agent_id,
                                     request.operation, request.target)
        after = self._endpoint.count
        effect = after - before
        consistent_allow = (outcome.allowed and outcome.executed and effect == 1 and
                            outcome.endpoint_before == before and outcome.endpoint_after == after)
        consistent_deny = (not outcome.allowed and not outcome.executed and effect == 0 and
                           outcome.endpoint_before == before and outcome.endpoint_after == after)
        status = "ALLOWED" if consistent_allow else "DENIED" if consistent_deny else "INCONCLUSIVE"
        return ToolResponse(workflow.workflow_id, True, outcome.allowed, effect == 1,
                            status, "GATE", outcome.reason, before, after)

    def _deny(self, workflow: Workflow, reason: str, before: int) -> ToolResponse:
        after = self._endpoint.count
        status = "DENIED" if before == after else "INCONCLUSIVE"
        return ToolResponse(workflow.workflow_id, True, False, before != after,
                            status, "BINDING", reason, before, after)
