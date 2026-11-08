"""Deterministic evidence for the inherited-socket process experiment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from boundary_proof.chain import canonical, digest

from .harness import ProcessHarness, request


def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def normalized_response(response: dict[str, object], actor) -> dict[str, object]:
    peer = response["peer"]
    return {**{key: value for key, value in response.items() if key != "peer"},
            "peer": {"channel": actor.channel,
                     "registered_pid_matches_spawned_process": peer["registered_pid"] == actor.pid,
                     "service_uid_matches_harness": peer["service_uid"] == os.getuid(),
                     "identity_source": peer["identity_source"],
                     "os_credentials_verified": peer["os_credentials_verified"]}}


def run_reference_scenario() -> dict[str, object]:
    events: list[dict[str, object]] = []
    with ProcessHarness() as harness:
        alice = harness.spawn_agent("alice", "agent-a")
        events.append({"type": "PROCESS_BOUNDARY", "service_role": "trusted_enforcement",
                       "agent_role": "untrusted_agent_alice",
                       "distinct_pids": harness.service.pid != alice.pid,
                       "protected_module_importable_from_agent": alice.ready["protected_module_importable"],
                       "ipc": "inherited_AF_UNIX_SOCK_DGRAM_socketpair",
                       "identity_trust": "TRUSTED_HARNESS_CHANNEL_REGISTRATION",
                       "os_credentials_verified": False})
        grant = harness.issue(alice)
        events.append({"type": "GRANT_ISSUED", "grant": {key: grant[key] for key in
                       ("grant_id", "principal", "agent", "operation", "target")}})
        original = request(grant["grant_id"])
        alice.command({"type": "start", "request": original})
        events.append({"type": "WORKFLOW_STARTED", "request": original,
                       "endpoint_count": harness.state()["endpoint_count"]})
        harness.admin({"type": "revoke", "grant_id": grant["grant_id"]})
        events.append({"type": "GRANT_REVOKED", "grant_id": grant["grant_id"],
                       "endpoint_count": harness.state()["endpoint_count"]})
        denied = normalized_response(alice.command({"type": "resume"})["response"], alice)
        events.append({"type": "IPC_RESPONSE", "case": "revoked", "request": original,
                       "response": denied, "independent_endpoint_count": harness.state()["endpoint_count"]})

        fresh = harness.issue(alice)
        events.append({"type": "GRANT_ISSUED", "grant": {key: fresh[key] for key in
                       ("grant_id", "principal", "agent", "operation", "target")}})
        fresh_request = request(fresh["grant_id"])
        alice.command({"type": "start", "request": fresh_request})
        events.append({"type": "WORKFLOW_STARTED", "request": fresh_request,
                       "endpoint_count": harness.state()["endpoint_count"]})
        allowed = normalized_response(alice.command({"type": "resume"})["response"], alice)
        events.append({"type": "IPC_RESPONSE", "case": "fresh", "request": fresh_request,
                       "response": allowed, "independent_endpoint_count": harness.state()["endpoint_count"]})

        bob = harness.spawn_agent("bob", "agent-a")
        events.append({"type": "AGENT_REGISTERED", "agent_role": "untrusted_agent_bob",
                       "distinct_pids": bob.pid != alice.pid and bob.pid != harness.service.pid,
                       "identity_trust": "TRUSTED_HARNESS_CHANNEL_REGISTRATION"})
        bypass_cases = (
            (alice, "direct_state_write", {"type": "set_count", "value": 999}, "UNSUPPORTED_OPERATION"),
            (alice, "missing_grant", request(""), "MISSING_GRANT"),
            (alice, "wrong_operation", request(fresh["grant_id"], operation="delete_case"), "OPERATION_MISMATCH"),
            (alice, "wrong_target", request(fresh["grant_id"], target="case-200"), "TARGET_MISMATCH"),
            (bob, "forged_identity", request(fresh["grant_id"]), "IDENTITY_CLAIM_MISMATCH"),
        )
        bypass_results = []
        for actor, label, payload, expected in bypass_cases:
            response = normalized_response(
                actor.command({"type": "raw", "request": payload})["response"], actor)
            count = harness.state()["endpoint_count"]
            bypass_results.append((response, expected, count))
            events.append({"type": "IPC_RESPONSE", "case": label, "request": payload,
                           "response": response, "independent_endpoint_count": count})

        race_grant = harness.issue(alice)
        events.append({"type": "GRANT_ISSUED", "grant": {key: race_grant[key] for key in
                       ("grant_id", "principal", "agent", "operation", "target")}})
        race_request = request(race_grant["grant_id"])
        alice.command({"type": "start", "request": race_request})
        events.append({"type": "WORKFLOW_STARTED", "request": race_request,
                       "endpoint_count": harness.state()["endpoint_count"]})
        harness.admin({"type": "arm_race"})
        alice.send({"type": "resume"})
        harness.wait_race("checked", True)
        events.append({"type": "GATE_CHECK_REACHED", "grant_id": race_grant["grant_id"]})
        harness.admin({"type": "revoke_async", "grant_id": race_grant["grant_id"]})
        time.sleep(0.05)
        interleaved = harness.admin({"type": "race_status"})["revocation_done"]
        events.append({"type": "REVOCATION_ATTEMPTED", "committed_before_release": interleaved})
        harness.admin({"type": "release_race"})
        raced = normalized_response(alice.read()["response"], alice)
        events.append({"type": "IPC_RESPONSE", "case": "race_action", "request": race_request,
                       "response": raced, "independent_endpoint_count": harness.state()["endpoint_count"]})
        harness.wait_race("revocation_done", True)
        events.append({"type": "GRANT_REVOKED", "grant_id": race_grant["grant_id"],
                       "endpoint_count": harness.state()["endpoint_count"]})
        later = normalized_response(
            alice.command({"type": "raw", "request": race_request})["response"], alice)
        final_state = harness.state()
        events.append({"type": "IPC_RESPONSE", "case": "after_race_revoke",
                       "request": race_request, "response": later,
                       "independent_endpoint_count": final_state["endpoint_count"]})
        events.append({"type": "CORE_EVENT_ORDER", "events": final_state["core_events"]})

        passed = (harness.service.pid != alice.pid and not alice.ready["protected_module_importable"] and
                  denied["status"] == "DENIED" and denied["reason"] == "AUTHORITY_REVOKED" and
                  denied["endpoint_before"] == denied["endpoint_after"] == 0 and
                  allowed["status"] == "ALLOWED" and allowed["endpoint_before"] == 0 and
                  allowed["endpoint_after"] == 1 and
                  all(response["status"] == "DENIED" and response["reason"] == expected and count == 1
                      for response, expected, count in bypass_results) and
                  not interleaved and raced["status"] == "ALLOWED" and
                  raced["endpoint_before"] == 1 and raced["endpoint_after"] == 2 and
                  later["status"] == "DENIED" and later["reason"] == "AUTHORITY_REVOKED" and
                  final_state["endpoint_count"] == 2 and
                  max(index for index, kind in enumerate(final_state["core_events"])
                      if kind == "ACTION_COMMITTED") <
                  max(index for index, kind in enumerate(final_state["core_events"])
                      if kind == "GRANT_REVOKED"))
    body = {"profile": "kimura-process-isolation-phase1a2/1", "events": events,
            "endpoint_count": final_state["endpoint_count"],
            "verdict": "GO" if passed else "NO-GO",
            "limitations": ["Agent channel identity is registered by trusted harness, not kernel-authenticated per message",
                            "Same-UID hostile processes may obtain service files or descriptors",
                            "Only inherited local IPC descriptors are exposed; no public listener",
                            "Local hash integrity does not authenticate provenance"]}
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
            raise ValueError("process evidence did not meet the local contract")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(canonical(evidence) + b"\n")
        print(json.dumps({"status": "PASS", "path": str(args.output)}, sort_keys=True))
        return 0
    raw = args.verify.read_bytes()
    evidence = json.loads(raw, object_pairs_hook=unique_keys)
    valid = raw == canonical(evidence) + b"\n" and verify_evidence(evidence)
    print(json.dumps({"status": "PASS" if valid else "INCONCLUSIVE",
                      "path": str(args.verify)}, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
