"""Deterministic local evidence for the Phase 1A workflow."""

from __future__ import annotations

from dataclasses import asdict

from boundary_proof import ReferenceChain
from boundary_proof.chain import digest

from .adapter import AgentToolAdapter, ToolRequest, ToolResponse
from .identity import BoundGrantAuthority, SimulatedIdentityProvider


def _response(response: ToolResponse) -> dict[str, object]:
    return {**asdict(response), "reported_success": response.reported_success}


def run_reference_scenario() -> dict[str, object]:
    chain = ReferenceChain()
    identities = SimulatedIdentityProvider()
    identities.register("session-42", "user-42", "agent-7")
    bindings = BoundGrantAuthority(chain.authorization, identities)
    adapter = AgentToolAdapter(chain.gate, chain.endpoint, bindings, identities)
    grant = bindings.issue("session-42", "approve_case", "case-100")
    request = ToolRequest("user-42", "agent-7", "approve_case", "case-100", grant)
    workflow = adapter.begin(request, "session-42")
    events: list[dict[str, object]] = [
        {"type": "WORKFLOW_STARTED", "workflow_id": workflow.workflow_id,
         "request": {"user_id": request.user_id, "agent_id": request.agent_id,
                     "operation": request.operation, "target": request.target},
         "grant": {"grant_id": grant.grant.grant_id, "principal_id": grant.principal_id,
                   "agent_id": grant.agent_id, "operation": grant.operation,
                   "target": grant.target},
         "simulated_identity": asdict(workflow.started_identity),
         "identity_trust": "SIMULATED_SESSION_REGISTRY",
         "endpoint_count": chain.endpoint.count},
    ]
    bindings.revoke(grant)
    events.append({"type": "GRANT_REVOKED", "grant_id": grant.grant.grant_id,
                   "endpoint_count": chain.endpoint.count})
    denied = adapter.resume(workflow, "session-42")
    events.append({"type": "TOOL_COMPLETED", "workflow_id": workflow.workflow_id,
                   "gate_decision": {"allowed": denied.authorized, "reason": denied.reason},
                   "endpoint_before": denied.endpoint_before,
                   "endpoint_after": denied.endpoint_after,
                   "tool_response": _response(denied)})

    fresh_grant = bindings.issue("session-42", "approve_case", "case-100")
    fresh_workflow = adapter.begin(ToolRequest("user-42", "agent-7", "approve_case",
                                               "case-100", fresh_grant), "session-42")
    events.append({"type": "WORKFLOW_STARTED", "workflow_id": fresh_workflow.workflow_id,
                   "request": {"user_id": "user-42", "agent_id": "agent-7",
                               "operation": "approve_case", "target": "case-100"},
                   "grant": {"grant_id": fresh_grant.grant.grant_id,
                             "principal_id": fresh_grant.principal_id,
                             "agent_id": fresh_grant.agent_id,
                             "operation": fresh_grant.operation, "target": fresh_grant.target},
                   "simulated_identity": asdict(fresh_workflow.started_identity),
                   "identity_trust": "SIMULATED_SESSION_REGISTRY",
                   "endpoint_count": chain.endpoint.count})
    allowed = adapter.resume(fresh_workflow, "session-42")
    events.append({"type": "TOOL_COMPLETED", "workflow_id": fresh_workflow.workflow_id,
                   "gate_decision": {"allowed": allowed.authorized, "reason": allowed.reason},
                   "endpoint_before": allowed.endpoint_before,
                   "endpoint_after": allowed.endpoint_after,
                   "tool_response": _response(allowed)})

    passed = (denied.status == "DENIED" and denied.reason == "AUTHORITY_REVOKED" and
              not denied.reported_success and denied.endpoint_before == denied.endpoint_after == 0 and
              allowed.status == "ALLOWED" and allowed.reported_success and
              allowed.endpoint_before == 0 and allowed.endpoint_after == 1 and
              chain.endpoint.count == 1)
    body = {"profile": "kimura-agent-tool-phase1a/1", "events": events,
            "endpoint_count": chain.endpoint.count,
            "verdict": "GO" if passed else "NO-GO",
            "limitations": ["Identity is supplied by a local session registry, not cryptographically authenticated",
                            "User-agent binding is adapter-local; Phase 0 grant contains agent, operation, target",
                            "Synthetic in-memory endpoint count; no real case system",
                            "Local hash integrity only; no independent authenticity anchor"]}
    return {**body, "evidence_sha256": digest(body)}


def verify_evidence(evidence: object) -> bool:
    return type(evidence) is dict and evidence == run_reference_scenario() and evidence.get("verdict") == "GO"
