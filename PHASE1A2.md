# Phase 1A.2 — local process-isolated enforcement spike

## Baseline

The branch began at `2405c2cb7c3745e17f3ef1063ffc1cc51f4beb2b` with a clean working tree. Phase 0, Phase 1A, and Phase 1A.1 ran 4/4, 5/5, and 10/10 tests respectively. All 11 existing mutants were detected with zero mutant errors. All three existing canonical evidence examples verified.

## Architecture

The trusted service is a separate Python process. It owns `ReferenceChain`, including authorization state, the Gate, and the endpoint. A standard-library-only agent script runs in another process from a temporary directory with Python isolation flags (`-I -S`). Its protected package import probe returns false. The trusted harness creates inherited `AF_UNIX` datagram socketpairs before starting either child. It passes one descriptor to each agent and the other descriptor to the service. There is no pathname or public network listener. The service's agent-facing protocol has one operation, `execute`; `state`, `set_count`, grant issuance, and revocation are not exposed on it.

The harness alone holds the service's stdin control pipe for process registration, grant issue and revocation, race coordination, and independent state observation. The service issues a Phase 0 grant scoped to agent, operation, and target, then records the harness-registered principal and agent against the grant reference. Each IPC request supplies principal, agent, operation, target, and grant reference. The service checks those claims against its own registered channel and grant records before calling the unchanged public `Gate.execute`. The Gate checks live revocation and holds its shared lock from check through endpoint commitment. The endpoint count is read independently through the trusted control pipe.

**Identity trust:** the OS gives the processes separate address spaces and file descriptors. The agent cannot invoke the endpoint through the defined IPC protocol or import its package in the provided isolated launch. The sandbox prevented binding a pathname Unix socket and prevented a child from wrapping an inherited socket descriptor to read per-message peer credentials. The experiment therefore binds identity to a descriptor that the trusted harness assigned to a child process; the service does **not** kernel-authenticate PID, UID, or human identity on each message. The recorded PID is a harness registration claim. A real system would need authenticated peer credentials or another trusted identity mechanism, plus permissions that prevent a hostile same-UID process from obtaining the service's descriptors, files, or memory.

## Checks and ordering

The workflow starts in the agent, pauses, and resumes after the service revokes its grant. The service returns `DENIED / AUTHORITY_REVOKED`; the independent endpoint count stays at zero. A fresh grant commits once. Direct `execute` calls also pass through the same checks. Forged identity, missing or unknown grant, wrong operation, wrong target, and unsupported state-write commands are denied without endpoint mutation.

For the cross-process race, the trusted harness arms a test hook. An agent request reaches the Gate's live check and pauses before endpoint commitment while the Gate holds its shared `RLock`. A concurrent service revocation attempt starts but cannot commit until the action is released and committed. `ACTION_COMMITTED` precedes `GRANT_REVOKED` in the service's core ledger. A later request is denied. The action linearizes at the endpoint count increment; revocation linearizes at the grant active-state update. Process separation itself does not provide this atomicity; the unchanged Phase 0 lock does.

## Run

Python 3.12+ on a Unix-like OS is required. No third-party Python package, model, device, customer identity, public listener, or external network is used.

```bash
python3 -m unittest tests.test_chain tests.test_phase1a tests.test_phase1a1 tests.test_phase1a2 -v
python3 mutation_check.py
python3 phase1a_mutation_check.py
python3 phase1a1_mutation_check.py
python3 phase1a2_mutation_check.py
python3 -m process_isolation.evidence --verify examples/phase1a2-reference-evidence.json
```

The four Phase 1A.2 mutants run on temporary source copies: bypassing the Gate, trusting request identity claims, removing the Gate's check-to-commit lock, and returning false success after denial. The results and detecting assertions are in `examples/phase1a2-mutation-results.json`.

The canonical evidence in `examples/phase1a2-reference-evidence.json` records process roles, channel trust, grant and request scope, IPC responses, independent endpoint counts, and event order. Volatile PIDs and UID values are replaced by harness-computed relation flags so a fresh run reproduces the same bytes. Those flags do not verify the sender of an individual message. The evidence does not claim OS-authenticated identity or independently authenticated provenance. Local SHA-256 only checks integrity against the current code's deterministic projection.

This is a bounded experiment. Same-UID hostile processes, descriptor theft, process memory access, durable state, restart recovery, distributed atomicity, and production authentication remain outside its guarantee. The result supports a local process-boundary claim for the defined IPC interface, with identity and hostile-process isolation still requiring validation.
