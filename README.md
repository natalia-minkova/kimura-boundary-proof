# Kimura Boundary Proof — local reference experiments

## Why Kimura Exists

An AI agent may start a workflow with valid authorization, then reach the tool execution step after that authorization has been revoked or changed. Checking only when the workflow starts can leave a gap between the original request and the action that changes state.

Kimura Boundary Proof provides reproducible reference tests for execution-time revocation, simulated principal and agent identity binding, operation and target scope binding, and check-to-commit races. The included agent-tool and process experiments use synthetic local state. This repository demonstrates those specific workflows; it does not automatically audit an arbitrary external AI agent or authenticate real users.

## Quick Start

From the repository root, run:

```bash
python3 evaluate.py
```

Requirements: Python 3.12 or later, a compatible POSIX environment with local Unix sockets and subprocess support, and writable temporary storage. No third-party Python packages are required. The command runs the tests, disposable mutation checks, and canonical evidence verification without changing the checked-in examples. A passing result shows that this reference implementation reproduces its stated behavior locally; it is not independent security validation. See `EXTERNAL_EVALUATION.md` for the full environment assumptions and security limits.

## Independent developer evaluation

From a clean local clone or the evaluation archive, run `python3 evaluate.py`. This one command runs all 23 tests, checks all 15 disposable mutations, verifies four canonical evidence examples, and reproduces each example in temporary files. It requires Python 3.12+ and a Unix-like system that permits local `AF_UNIX` datagram socketpairs, inherited file descriptors, subprocesses, and writable temporary storage. No third-party package or network access is needed. See `EXTERNAL_EVALUATION.md` for installation, packaging, and the exact security and provenance limits. A local PASS is reproducibility evidence, not independent security validation.

## Phase 0

A minimal **software-only verification-method prototype** for authority continuity. It is not a production authorization service. The reference workflow issues a grant, commits one action, revokes the grant, denies a later action without changing endpoint state, issues a fresh grant, and commits a second action. The controller is scripted; no AI model, aircraft, MAVLink, external service, or customer data is involved.

## Run from a clean environment

Python 3.12 or later is sufficient for the Phase 0 commands below. Git is needed to clone the repository, but not to run the code. The project has **no third-party Python dependencies**. Do not install packages to run it.

```bash
python3 -m venv .venv
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m boundary_proof --verify examples/reference-evidence.json
.venv/bin/python mutation_check.py
```

To generate a new evidence file without overwriting the example:

```bash
.venv/bin/python -m boundary_proof --output examples/my-run.json
.venv/bin/python -m boundary_proof --verify examples/my-run.json
```

Use a fresh output filename. The example is canonical UTF-8 JSON with sorted keys, compact separators, sequential events, a SHA-256 hash chain, an endpoint count, and a final local digest. Its hash does **not** authenticate who produced it. The verifier replays the exact Phase 0 sequence from the original code and checks the event chain, decisions, and observed endpoint counts. A coherent local rewrite is still possible without an external trust anchor.

## Component contract

- `AuthorizationService.issue(principal, operation, target)` creates a scoped grant; `revoke(grant)` changes live state; `is_current(grant)` reads live state.
- `Gate.execute` checks principal, operation, target, and current authority at execution time. It records the decision and calls the endpoint only after approval.
- `AgentController` holds a grant and uses only the Gate in this reference workflow.
- `ActionEndpoint` maintains an independently readable in-memory count and accepts a commit only with the Gate's local capability object. Its Python-private methods are not a hostile-code isolation mechanism.

**Atomicity mechanism:** all four components share one process-local `threading.RLock`. `Gate.execute` holds it across authority checking, the test hook, and endpoint commitment. Revocation linearizes at the active-state update in `AuthorizationService.revoke`; execution linearizes at the count increment in `ActionEndpoint._commit`. The hook pauses *after* the live check and *before* that increment without releasing the lock. The protected test records `ACTION_COMMITTED` before `GRANT_REVOKED`. A disposable mutant drops only the outer Gate lock: its test records `GRANT_REVOKED` before `ACTION_COMMITTED` and fails. Thus the race test exercises a real check-to-commit window and detects removal of atomicity.

## Mutation meta-check

`mutation_check.py` copies the package and tests into disposable temporary directories. It changes only those copies, runs the same standard-library tests, and writes `examples/mutation-results.json`. Mutation 1 caches the first authorization decision: the revoked action executes, endpoint count becomes 2, and the revoked-result assertion fails. Mutation 2 removes the Gate's outer lock: revocation commits between the authorization decision and action commit, and the race assertion fails. The original implementation remains unchanged. See the results file for exact failing tests and event order.

## Scope and IP notes

This is a single-process transaction model. It does not establish distributed atomicity, durable storage, authentication, resistance to malicious code running in the same Python process, or production readiness. `AgentController` not bypassing the Gate is a reference-workflow property, not a sandbox boundary. Local hashes are integrity aids, not independent evidence provenance. No claim is made about real agent-model behavior.

The original Phase 0 code is licensed under Apache-2.0; the individual copyright holder is Natalia Minkova, trading as Cyber Kimura. Kimura's authority-lineage, execution-time enforcement, independent state observation, exact-retest, and mutation-testing **concepts** informed the design. The source comparison found no prior Kimura implementation copied into this repository. See `LICENSE`, `NOTICE`, `IP_REFERENCES.md`, and `DEPENDENCIES.md` for attribution, provenance, and review limits.

## Phase 1A integration spike

See `PHASE1A.md` for the synthetic agent-tool adapter, its public API, evidence commands, tests, mutation checks, and limits.

See `PHASE1A1.md` for the simulated identity and grant-binding hardening, scope controls, and in-process bypass assessment.

See `PHASE1A2.md` for the separate-process enforcement experiment, its local IPC protocol, tests, evidence, and trust limits.
