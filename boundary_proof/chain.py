"""Original, in-process authority-continuity reference chain.

The shared reentrant lock orders revocation and check-plus-endpoint-commit. This
module does not assert distributed or cross-process atomicity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from threading import RLock
from typing import Callable


def canonical(value: object) -> bytes:
    """Deterministic UTF-8 JSON for the deliberately small local evidence schema."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Grant:
    grant_id: str
    principal: str
    operation: str
    target: str


@dataclass(frozen=True)
class Outcome:
    allowed: bool
    reason: str
    executed: bool
    endpoint_before: int
    endpoint_after: int

    @property
    def reported_success(self) -> bool:
        return self.allowed and self.executed and self.endpoint_after == self.endpoint_before + 1


class EvidenceLedger:
    """Local hash-chain journal. It is not an independent authenticity anchor."""

    def __init__(self, lock: RLock) -> None:
        self._lock = lock
        self._events: list[dict[str, object]] = []

    def record(self, kind: str, data: dict[str, object]) -> None:
        with self._lock:
            body = {"sequence": len(self._events) + 1, "type": kind,
                    "previous_hash": self._events[-1]["hash"] if self._events else "0" * 64,
                    "data": data}
            self._events.append({**body, "hash": digest(body)})

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return json.loads(canonical(self._events))


class AuthorizationService:
    """Live grant store; no cached authorization decision."""

    def __init__(self, lock: RLock, ledger: EvidenceLedger) -> None:
        self._lock = lock
        self._ledger = ledger
        self._grants: dict[str, tuple[Grant, bool]] = {}
        self._next = 1

    def issue(self, principal: str, operation: str, target: str) -> Grant:
        if any(type(value) is not str or not value for value in (principal, operation, target)):
            raise ValueError("grant scope requires nonempty strings")
        with self._lock:
            grant = Grant(f"g{self._next}", principal, operation, target)
            self._next += 1
            self._grants[grant.grant_id] = (grant, True)
            self._ledger.record("GRANT_ISSUED", asdict(grant))
            return grant

    def revoke(self, grant: Grant) -> None:
        with self._lock:
            if self.inspect(grant) == "INVALID_GRANT":
                raise ValueError("unknown or modified grant")
            if self.inspect(grant) == "REVOKED":
                raise ValueError("grant already revoked")
            self._grants[grant.grant_id] = (grant, False)  # Revocation linearizes here.
            self._ledger.record("GRANT_REVOKED", {"grant_id": grant.grant_id})

    def inspect(self, grant: Grant) -> str:
        with self._lock:
            if type(grant) is not Grant or grant.grant_id not in self._grants or self._grants[grant.grant_id][0] != grant:
                return "INVALID_GRANT"
            return "CURRENT" if self._grants[grant.grant_id][1] else "REVOKED"

    def is_current(self, grant: Grant) -> bool:
        with self._lock:
            return self.inspect(grant) == "CURRENT"


class ActionEndpoint:
    """In-memory endpoint; the reference workflow exposes no direct commit API."""

    def __init__(self, lock: RLock, ledger: EvidenceLedger) -> None:
        self._lock = lock
        self._ledger = ledger
        self._count = 0
        self._gate_key = object()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def _commit(self, gate_key: object, grant: Grant) -> tuple[int, int]:
        if gate_key is not self._gate_key:
            raise PermissionError("endpoint requires gate authorization")
        with self._lock:
            before = self._count
            self._count += 1  # Action linearizes here, under the shared lock.
            after = self._count
            self._ledger.record("ACTION_COMMITTED", {"grant_id": grant.grant_id,
                                                      "endpoint_before": before,
                                                      "endpoint_after": after})
            return before, after


class Gate:
    """Execution-time check and endpoint commit in one local critical section."""

    def __init__(self, authorization: AuthorizationService,
                 endpoint: ActionEndpoint, ledger: EvidenceLedger) -> None:
        if authorization._lock is not endpoint._lock or authorization._lock is not ledger._lock:
            raise ValueError("all components must share the same transaction lock")
        self._authorization = authorization
        self._endpoint = endpoint
        self._ledger = ledger
        self._lock = authorization._lock

    def execute(self, grant: Grant, principal: str, operation: str, target: str,
                *, after_check: Callable[[], None] | None = None) -> Outcome:
        with self._lock:  # ATOMIC_WINDOW
            before = self._endpoint.count
            scope = {"principal": principal, "operation": operation, "target": target}
            if type(grant) is not Grant:
                current = False
                reason = "INVALID_GRANT"
            elif scope != {"principal": grant.principal, "operation": grant.operation,
                            "target": grant.target}:
                current = False
                reason = "SCOPE_MISMATCH"
            else:
                current = self._authorization.is_current(grant)  # LIVE_AUTHORITY_CHECK
                reason = "CURRENT_AUTHORITY" if current else (
                    "AUTHORITY_REVOKED" if self._authorization.inspect(grant) == "REVOKED"
                    else "INVALID_GRANT")
            grant_id = grant.grant_id if type(grant) is Grant else "INVALID"
            self._ledger.record("ACTION_REQUESTED", {"grant_id": grant_id, **scope})
            self._ledger.record("AUTHORIZATION_DECISION", {"grant_id": grant_id,
                                                            "allowed": current, "reason": reason,
                                                            "endpoint_before": before})
            if not current:
                after = self._endpoint.count
                self._ledger.record("ACTION_OUTCOME", {"grant_id": grant_id,
                                                       "executed": False,
                                                       "endpoint_before": before,
                                                       "endpoint_after": after})
                return Outcome(False, reason, False, before, after)
            if after_check is not None:
                after_check()  # Test-only synchronization point; lock remains held.
            committed_before, committed_after = self._endpoint._commit(self._endpoint._gate_key, grant)
            self._ledger.record("ACTION_OUTCOME", {"grant_id": grant_id,
                                                   "executed": True,
                                                   "endpoint_before": committed_before,
                                                   "endpoint_after": committed_after})
            return Outcome(True, reason, True, committed_before, committed_after)


class AgentController:
    """Reference controller holds a grant and can act only via its Gate."""

    def __init__(self, grant: Grant, gate: Gate) -> None:
        self._grant = grant
        self._gate = gate

    def request(self, *, after_check: Callable[[], None] | None = None) -> Outcome:
        return self._gate.execute(self._grant, self._grant.principal,
                                  self._grant.operation, self._grant.target,
                                  after_check=after_check)


class ReferenceChain:
    def __init__(self) -> None:
        lock = RLock()
        self.ledger = EvidenceLedger(lock)
        self.authorization = AuthorizationService(lock, self.ledger)
        self.endpoint = ActionEndpoint(lock, self.ledger)
        self.gate = Gate(self.authorization, self.endpoint, self.ledger)

    def evidence(self) -> dict[str, object]:
        events = self.ledger.snapshot()
        body = {"profile": "kimura-boundary-proof-local/1",
                "model": "ORIGINAL_SOFTWARE_ONLY_REFERENCE",
                "events": events, "endpoint_count": self.endpoint.count,
                "event_chain_head": events[-1]["hash"] if events else "0" * 64,
                "limitations": ["Local hash integrity only; no external authenticity anchor",
                                "Single-process shared-lock model; no distributed guarantee",
                                "Scripted controller; no AI model or external service"]}
        return {**body, "evidence_sha256": digest(body)}


def run_reference_scenario() -> dict[str, object]:
    chain = ReferenceChain()
    g = chain.authorization.issue("agent-1", "apply", "target-1")
    first = AgentController(g, chain.gate).request()
    chain.authorization.revoke(g)
    denied = AgentController(g, chain.gate).request()
    g2 = chain.authorization.issue("agent-1", "apply", "target-1")
    fresh = AgentController(g2, chain.gate).request()
    if not (first.reported_success and not denied.allowed and
            denied.reason == "AUTHORITY_REVOKED" and fresh.reported_success and
            chain.endpoint.count == 2):
        raise AssertionError("reference scenario did not meet its state contract")
    return chain.evidence()


def verify_evidence(evidence: dict[str, object]) -> bool:
    """Reproject this exact Phase 0 scenario; coherent local edits still need an anchor."""
    if type(evidence) is not dict or set(evidence) != {"profile", "model", "events", "endpoint_count",
                                                     "event_chain_head", "limitations", "evidence_sha256"}:
        return False
    body = {k: v for k, v in evidence.items() if k != "evidence_sha256"}
    try:
        if evidence != run_reference_scenario() or evidence["evidence_sha256"] != digest(body):
            return False
        previous = "0" * 64
        for number, event in enumerate(evidence["events"], 1):
            unsigned = {k: v for k, v in event.items() if k != "hash"}
            if (set(event) != {"sequence", "type", "previous_hash", "data", "hash"} or
                event["sequence"] != number or event["previous_hash"] != previous or
                event["hash"] != digest(unsigned)):
                return False
            previous = event["hash"]
        return previous == evidence["event_chain_head"]
    except (TypeError, ValueError, KeyError):
        return False
