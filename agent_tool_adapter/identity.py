"""Simulated local identity and grant binding for the Phase 1A.1 harness."""

from __future__ import annotations

from dataclasses import dataclass

from boundary_proof import AuthorizationService, Grant


@dataclass(frozen=True)
class SimulatedIdentity:
    principal_id: str
    agent_id: str


class SimulatedIdentityProvider:
    """Harness-owned session registry; no cryptographic authentication."""

    def __init__(self) -> None:
        self._sessions: dict[str, SimulatedIdentity] = {}

    def register(self, session_id: str, principal_id: str, agent_id: str) -> None:
        if any(type(value) is not str or not value
               for value in (session_id, principal_id, agent_id)):
            raise ValueError("session and identities require nonempty strings")
        if session_id in self._sessions:
            raise ValueError("session already registered")
        self._sessions[session_id] = SimulatedIdentity(principal_id, agent_id)

    def resolve(self, session_id: str) -> SimulatedIdentity | None:
        return self._sessions.get(session_id) if type(session_id) is str else None


@dataclass(frozen=True)
class BoundGrant:
    grant: Grant
    principal_id: str
    agent_id: str
    operation: str
    target: str


class BoundGrantAuthority:
    """Issues a Phase 0 grant and records its simulated user-agent binding."""

    def __init__(self, authorization: AuthorizationService,
                 identities: SimulatedIdentityProvider) -> None:
        self._authorization = authorization
        self._identities = identities
        self._issued: dict[str, BoundGrant] = {}

    def issue(self, session_id: str, operation: str, target: str) -> BoundGrant:
        identity = self._identities.resolve(session_id)
        if identity is None:
            raise ValueError("registered session required to issue a grant")
        grant = self._authorization.issue(identity.agent_id, operation, target)
        binding = BoundGrant(grant, identity.principal_id, identity.agent_id,
                             operation, target)
        self._issued[grant.grant_id] = binding
        return binding

    def is_issued(self, binding: BoundGrant) -> bool:
        return (type(binding) is BoundGrant and
                type(binding.grant) is Grant and
                self._issued.get(binding.grant.grant_id) is binding)

    def revoke(self, binding: BoundGrant) -> None:
        if not self.is_issued(binding):
            raise ValueError("unknown or modified bound grant")
        self._authorization.revoke(binding.grant)
