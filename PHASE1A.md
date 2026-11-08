# Phase 1A — synthetic agent-tool integration spike

This spike models an enterprise agent calling `approve_case(case-100)` on behalf of `user-42`. It uses the unmodified Phase 0 Gate and in-memory endpoint. It does not connect to a case system, model, network, or customer data.

## Verified baseline

Before the feature branch was created, `main` was at `0b7f564ee81235e018c819cc132f276967c48d07` with a clean working tree. The complete Phase 0 enforcement suite ran 4 tests: 4 passed, 0 failures, 0 errors. The Phase 0 stale-authorization mutant ran 4 tests (1 passed, 3 failures, 0 errors); the removed-atomicity mutant ran 4 tests (3 passed, 1 failure, 0 errors). Both were detected. `examples/reference-evidence.json` verified as `PASS`.

## Run

Python 3.12+ is required. No third-party package is required.

```bash
python3 -m unittest tests.test_chain -v
python3 mutation_check.py
python3 -m unittest tests.test_phase1a -v
python3 phase1a_mutation_check.py
python3 -m boundary_proof --verify examples/reference-evidence.json
python3 -m agent_tool_adapter --verify examples/phase1a-reference-evidence.json
```

To reproduce the Phase 1A evidence in a fresh file, run `python3 -m agent_tool_adapter --output /tmp/phase1a-evidence.json`, then verify that file with `--verify`.

## Integration API

`ToolRequest(user_id, agent_id, operation, target, grant)` carries the original request claims and a `BoundGrant`. `AgentToolAdapter.begin(request, session_id)` records the simulated session identity without calling the Gate or endpoint. `AgentToolAdapter.resume(workflow, session_id)` re-resolves that identity, checks its binding and scope, calls the public `Gate.execute(grant, agent_id, operation, target)` for matching requests, and reads the public `ActionEndpoint.count` before and after. It returns `ToolResponse` with separate `requested`, `authorized`, and `executed` fields, the decision source and reason, observed counts, and an `ALLOWED`, `DENIED`, or `INCONCLUSIVE` status. Successful execution is reported only when the Gate reports an allowed commit and the observed count increases exactly once. See `PHASE1A1.md` for the identity binding and trust boundary.

The adapter uses no private Phase 0 grant store, lock, endpoint method, or capability. The Phase 0 grant scopes the **agent**, operation, and target; it has no user field. Phase 1A.1 adds an adapter-local principal-and-agent binding resolved from a simulated session registry. It is logical binding in a local mock, not cryptographic authentication.

## Workflow and controls

The deterministic reference sequence issues a valid grant, starts a workflow, revokes before `resume`, then checks that the Gate returns `AUTHORITY_REVOKED` and the actual endpoint count remains zero. A fresh grant for the same operation succeeds and increments the count once. Integration tests also deny agent, operation, and target mismatches. A claiming Gate test checks that a reported commit without an observed effect becomes `INCONCLUSIVE` and cannot report success.

The revocation occurs **before** the protected Gate transaction starts. This test makes no claim about revocation inside the Gate's check-to-commit section; Phase 0 tests that separately.

Three disposable mutants test (1) direct endpoint commitment that bypasses the Gate, (2) false success reporting after a denial, and (3) an authorization cache that is populated on grant issue and not invalidated on revocation. `phase1a_mutation_check.py` copies code and tests into temporary directories and records outcomes in `examples/phase1a-mutation-results.json`. It never edits the checked-in core.

## Evidence and threat model

`examples/phase1a-reference-evidence.json` records the original request, identities, grant ID and scope, workflow starts, revocation, Gate decisions, actual endpoint counts, tool responses, final verdict, and a canonical JSON SHA-256 digest. The verifier compares a canonical file to a fresh deterministic run. Local hashes detect accidental or isolated changes; they do not authenticate who produced the file. A coherent rewrite of code and evidence remains possible.

This is a single-process synthetic model. It does not prove user authentication, model behavior, hostile-process isolation, persistent or distributed atomicity, durability, or production readiness. The adapter reads endpoint state outside the Gate transaction; the sample workflow runs sequentially, so concurrent unrelated endpoint activity is outside its claim. Phase 0 grants are reusable until revoked; this spike does not provide retry idempotency or single-use approval.
