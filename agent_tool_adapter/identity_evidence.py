"""Canonical local evidence for simulated principal and agent binding."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from boundary_proof import ReferenceChain
from boundary_proof.chain import canonical, digest

from .adapter import AgentToolAdapter, ToolRequest, ToolResponse
from .identity import BoundGrant, BoundGrantAuthority, SimulatedIdentityProvider


def _unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _scope(binding: BoundGrant) -> dict[str, str]:
    return {"grant_id": binding.grant.grant_id, "principal_id": binding.principal_id,
            "agent_id": binding.agent_id, "operation": binding.operation,
            "target": binding.target}


def run_reference_scenario() -> dict[str, object]:
    chain = ReferenceChain()
    identities = SimulatedIdentityProvider()
    identities.register("alice-a", "alice", "agent-a")
    identities.register("bob-a", "bob", "agent-a")
    identities.register("alice-b", "alice", "agent-b")
    bindings = BoundGrantAuthority(chain.authorization, identities)
    adapter = AgentToolAdapter(chain.gate, chain.endpoint, bindings, identities)
    grant = bindings.issue("alice-a", "approve_case", "case-100")
    events: list[dict[str, object]] = [
        {"type": "GRANT_ISSUED", "grant": _scope(grant),
         "identity_trust": "SIMULATED_SESSION_REGISTRY"},
    ]
    results: dict[str, ToolResponse] = {}

    def start(label: str, binding: BoundGrant, session: str, *, user: str = "alice",
              agent: str = "agent-a", operation: str = "approve_case",
              target: str = "case-100"):
        request = ToolRequest(user, agent, operation, target, binding)
        workflow = adapter.begin(request, session)
        events.append({"type": "WORKFLOW_STARTED", "case": label,
                       "workflow_id": workflow.workflow_id,
                       "grant": _scope(binding),
                       "request": {"user_id": user, "agent_id": agent,
                                   "operation": operation, "target": target},
                       "simulated_identity": asdict(workflow.started_identity),
                       "identity_trust": "SIMULATED_SESSION_REGISTRY",
                       "endpoint_count": chain.endpoint.count})
        return workflow

    def finish(label: str, workflow, session: str) -> None:
        identity = identities.resolve(session)
        response = adapter.resume(workflow, session)
        results[label] = response
        events.append({"type": "AUTHORIZATION_RESULT", "case": label,
                       "workflow_id": workflow.workflow_id,
                       "continuation_identity": asdict(identity) if identity else None,
                       "identity_trust": "SIMULATED_SESSION_REGISTRY",
                       "authorization_decision": {"allowed": response.authorized,
                                                  "source": response.decision_source,
                                                  "reason": response.reason},
                       "endpoint_before": response.endpoint_before,
                       "endpoint_after": response.endpoint_after,
                       "execution_result": {**asdict(response),
                                            "reported_success": response.reported_success}})

    finish("alice_grant_bob", start("alice_grant_bob", grant, "bob-a", user="bob"),
           "bob-a")
    finish("agent_a_grant_agent_b",
           start("agent_a_grant_agent_b", grant, "alice-b", agent="agent-b"),
           "alice-b")
    finish("wrong_operation",
           start("wrong_operation", grant, "alice-a", operation="delete_case"),
           "alice-a")
    finish("wrong_target", start("wrong_target", grant, "alice-a", target="case-200"),
           "alice-a")
    finish("claimed_alice_bob_session",
           start("claimed_alice_bob_session", grant, "bob-a"), "bob-a")
    finish("continuation_changed", start("continuation_changed", grant, "alice-a"),
           "bob-a")
    revoked_workflow = start("revoked", grant, "alice-a")
    bindings.revoke(grant)
    events.append({"type": "GRANT_REVOKED", "grant_id": grant.grant.grant_id,
                   "endpoint_count": chain.endpoint.count})
    finish("revoked", revoked_workflow, "alice-a")
    fresh = bindings.issue("alice-a", "approve_case", "case-100")
    events.append({"type": "GRANT_ISSUED", "grant": _scope(fresh),
                   "identity_trust": "SIMULATED_SESSION_REGISTRY"})
    finish("fresh", start("fresh", fresh, "alice-a"), "alice-a")

    expected = {"alice_grant_bob": "PRINCIPAL_MISMATCH",
                "agent_a_grant_agent_b": "AGENT_MISMATCH",
                "wrong_operation": "OPERATION_MISMATCH",
                "wrong_target": "TARGET_MISMATCH",
                "claimed_alice_bob_session": "IDENTITY_CLAIM_MISMATCH",
                "continuation_changed": "WORKFLOW_IDENTITY_CHANGED",
                "revoked": "AUTHORITY_REVOKED"}
    denied = all(results[name].status == "DENIED" and
                 results[name].reason == reason and
                 results[name].endpoint_before == results[name].endpoint_after == 0 and
                 not results[name].reported_success
                 for name, reason in expected.items())
    allowed = results["fresh"]
    passed = (denied and allowed.status == "ALLOWED" and allowed.reported_success and
              allowed.endpoint_before == 0 and allowed.endpoint_after == 1 and
              chain.endpoint.count == 1)
    body = {"profile": "kimura-identity-binding-phase1a1/1", "events": events,
            "endpoint_count": chain.endpoint.count,
            "verdict": "GO" if passed else "NO-GO",
            "limitations": ["Session registry is a harness simulation, not authentication",
                            "Bound user identity is adapter-local; Phase 0 grant binds agent, operation, target",
                            "Python-private endpoint capability can be reached by hostile same-process code",
                            "Local SHA-256 is not independently authenticated provenance"]}
    return {**body, "evidence_sha256": digest(body)}


def verify_evidence(value: object) -> bool:
    return type(value) is dict and value == run_reference_scenario() and value.get("verdict") == "GO"


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output:
        evidence = run_reference_scenario()
        if not verify_evidence(evidence):
            raise ValueError("identity-binding evidence did not meet the contract")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(canonical(evidence) + b"\n")
        print(json.dumps({"status": "PASS", "path": str(args.output)}, sort_keys=True))
        return 0
    raw = args.verify.read_bytes()
    evidence = json.loads(raw, object_pairs_hook=_unique_keys)
    valid = raw == canonical(evidence) + b"\n" and verify_evidence(evidence)
    print(json.dumps({"status": "PASS" if valid else "INCONCLUSIVE",
                      "path": str(args.verify)}, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
