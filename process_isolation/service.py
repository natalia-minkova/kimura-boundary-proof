"""Trusted local enforcement process with a Unix-socket execute-only interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading

from boundary_proof import ReferenceChain


def send_line(stream, value: dict[str, object]) -> None:
    stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


class EnforcementService:
    def __init__(self) -> None:
        self.chain = ReferenceChain()
        self.identities: dict[int, tuple[int, str, str]] = {}
        self.grants: dict[str, tuple[object, str, str, str, str]] = {}
        self.data_lock = threading.RLock()
        self.stop = threading.Event()
        self.race_checked = threading.Event()
        self.race_release = threading.Event()
        self.revoke_done = threading.Event()
        self.race_armed = False

    def admin(self, command: dict[str, object]) -> dict[str, object]:
        kind = command.get("type")
        if kind == "register":
            channel = command.get("channel")
            pid = command.get("pid")
            principal = command.get("principal")
            agent = command.get("agent")
            if (type(channel) is not int or channel < 0 or
                    type(pid) is not int or pid <= 0 or
                    any(type(value) is not str or not value for value in (principal, agent))):
                return {"status": "ERROR", "reason": "INVALID_REGISTRATION"}
            with self.data_lock:
                if channel in self.identities:
                    return {"status": "ERROR", "reason": "ALREADY_REGISTERED"}
                self.identities[channel] = (pid, principal, agent)
            return {"status": "OK", "principal": principal, "agent": agent}
        if kind == "issue":
            channel = command.get("channel")
            operation = command.get("operation")
            target = command.get("target")
            with self.data_lock:
                identity = self.identities.get(channel) if type(channel) is int else None
                if identity is None:
                    return {"status": "ERROR", "reason": "UNREGISTERED_PROCESS"}
                try:
                    grant = self.chain.authorization.issue(identity[2], operation, target)
                except ValueError:
                    return {"status": "ERROR", "reason": "INVALID_SCOPE"}
                self.grants[grant.grant_id] = (grant, identity[1], identity[2], operation, target)
            return {"status": "OK", "grant_id": grant.grant_id,
                    "principal": identity[1], "agent": identity[2],
                    "operation": operation, "target": target}
        if kind in ("revoke", "revoke_async"):
            grant_id = command.get("grant_id")
            with self.data_lock:
                record = self.grants.get(grant_id) if type(grant_id) is str else None
            if record is None:
                return {"status": "ERROR", "reason": "INVALID_GRANT"}
            if kind == "revoke":
                try:
                    self.chain.authorization.revoke(record[0])
                except ValueError:
                    return {"status": "ERROR", "reason": "ALREADY_REVOKED"}
                return {"status": "OK", "grant_id": grant_id}

            self.revoke_done.clear()
            started = threading.Event()

            def revoke_worker():
                try:
                    started.set()
                    self.chain.authorization.revoke(record[0])
                finally:
                    self.revoke_done.set()

            threading.Thread(target=revoke_worker, daemon=True).start()
            started.wait(timeout=1)
            return {"status": "STARTED", "grant_id": grant_id}
        if kind == "state":
            return {"status": "OK", "endpoint_count": self.chain.endpoint.count,
                    "core_events": [event["type"] for event in self.chain.ledger.snapshot()]}
        if kind == "arm_race":
            self.race_checked.clear()
            self.race_release.clear()
            self.revoke_done.clear()
            self.race_armed = True
            return {"status": "OK"}
        if kind == "race_status":
            return {"status": "OK", "checked": self.race_checked.is_set(),
                    "revocation_done": self.revoke_done.is_set()}
        if kind == "release_race":
            self.race_release.set()
            return {"status": "OK"}
        if kind == "shutdown":
            self.stop.set()
            self.race_release.set()
            return {"status": "OK"}
        return {"status": "ERROR", "reason": "UNSUPPORTED_ADMIN_COMMAND"}

    def _race_hook(self) -> None:
        self.race_checked.set()
        if not self.race_release.wait(timeout=5):
            raise TimeoutError("race hook was not released")

    def execute(self, request: object, channel: int) -> dict[str, object]:
        before = self.chain.endpoint.count
        with self.data_lock:
            registered = self.identities.get(channel)  # CHANNEL_IDENTITY_CHECK
        peer = {"channel": channel, "registered_pid": registered[0] if registered else None,
                "identity_source": "TRUSTED_HARNESS_CHANNEL_REGISTRATION",
                "os_credentials_verified": False,
                "service_uid": os.getuid()}

        def deny(reason: str) -> dict[str, object]:
            after = self.chain.endpoint.count
            return {"status": "DENIED" if after == before else "INCONCLUSIVE",
                    "reason": reason, "authorized": False, "executed": False,
                    "endpoint_before": before, "endpoint_after": after,
                    "decision_source": "SERVICE_BINDING", "peer": peer}

        if type(request) is not dict or request.get("type") != "execute":
            return deny("UNSUPPORTED_OPERATION")
        with self.data_lock:
            identity = self.identities.get(channel)  # CHANNEL_IDENTITY_CHECK
            grant_id = request.get("grant_id")
            record = self.grants.get(grant_id) if type(grant_id) is str else None
        if identity is None:
            return deny("UNREGISTERED_CHANNEL")
        if type(grant_id) is not str or not grant_id:
            return deny("MISSING_GRANT")
        if record is None:
            return deny("INVALID_GRANT")
        _, principal, agent = identity
        claimed_principal = request.get("principal")
        claimed_agent = request.get("agent")
        if claimed_principal != principal or claimed_agent != agent:  # CLAIM_CHECK
            return deny("IDENTITY_CLAIM_MISMATCH")
        grant, bound_principal, bound_agent, operation, target = record
        if principal != bound_principal:
            return deny("PRINCIPAL_MISMATCH")
        if agent != bound_agent:
            return deny("AGENT_MISMATCH")
        if request.get("operation") != operation:
            return deny("OPERATION_MISMATCH")
        if request.get("target") != target:
            return deny("TARGET_MISMATCH")
        hook = self._race_hook if self.race_armed else None
        self.race_armed = False
        outcome = self.chain.gate.execute(grant, agent, operation, target,
                                          after_check=hook)  # LIVE_GATE_CHECK
        after = self.chain.endpoint.count
        executed = outcome.executed and outcome.endpoint_after == outcome.endpoint_before + 1
        status = "ALLOWED" if outcome.allowed and executed else "DENIED" if not outcome.allowed and not outcome.executed else "INCONCLUSIVE"
        return {"status": status, "reason": outcome.reason,
                "authorized": outcome.allowed, "executed": executed,
                "endpoint_before": outcome.endpoint_before,
                "endpoint_after": outcome.endpoint_after,
                "observed_endpoint_count": after,
                "decision_source": "GATE", "peer": peer}  # RESULT_RESPONSE


def handle_client(service: EnforcementService, fd: int, channel: int) -> None:
    try:
        while not service.stop.is_set():
            try:
                raw = os.read(fd, 16385)
                if not raw:
                    break
                if len(raw) > 16384:
                    response = {"status": "DENIED", "reason": "REQUEST_TOO_LARGE"}
                else:
                    response = service.execute(json.loads(raw), channel)
            except (ValueError, json.JSONDecodeError, OSError, TimeoutError) as error:
                response = {"status": "INCONCLUSIVE", "reason": type(error).__name__}
            os.write(fd, json.dumps(response, sort_keys=True,
                                    separators=(",", ":")).encode())
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service_fds", nargs="+", type=int)
    args = parser.parse_args()
    service = EnforcementService()

    def admin_loop():
        for line in sys.stdin:
            try:
                result = service.admin(json.loads(line))
            except (ValueError, TypeError) as error:
                result = {"status": "ERROR", "reason": type(error).__name__}
            send_line(sys.stdout, result)
            if service.stop.is_set():
                break
        service.stop.set()

    for channel, fd in enumerate(args.service_fds):
        threading.Thread(target=handle_client, args=(service, fd, channel),
                         daemon=True).start()
    send_line(sys.stdout, {"status": "READY"})
    admin_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
