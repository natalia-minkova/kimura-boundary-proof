# Phase 1A.1 — simulated identity and authority binding

## Verified baseline

The branch started from `075a4a42049534bce62b4ac073569d9b9c2ab87c` with a clean working tree. Phase 0 ran 4/4 tests, Phase 1A ran 5/5 tests, and both canonical examples verified. Both Phase 0 mutations and all three Phase 1A mutations were detected with no mutant test errors.

## Architecture findings

The Phase 0 `Grant` binds one `principal` string, operation, and target. `Gate.execute` compares caller-provided strings to that grant and checks live revocation under its shared lock. The Phase 0 controller forwards its stored grant and scope. Phase 1A used the agent ID as the Phase 0 principal, while its user ID was an unverified request field. None of these strings is cryptographically authenticated.

Phase 1A.1 keeps the Phase 0 core unchanged. A harness-owned `SimulatedIdentityProvider` maps local session handles to a principal and agent. `BoundGrantAuthority.issue(session, operation, target)` derives both identities from that registry, issues a Phase 0 grant for the agent, and records a bound user, agent, operation, and target. The adapter re-resolves the session on continuation, compares it to the start identity and the issued binding, and supplies the resolved agent ID to `Gate.execute`. Request identity strings are checked against the resolved identity; they do not create it. The Gate still performs execution-time authorization and endpoint commitment atomically. The adapter stores no authorization decision.

Explicit pre-Gate denial reasons are `AUTHENTICATION_REQUIRED`, `WORKFLOW_IDENTITY_CHANGED`, `IDENTITY_CLAIM_MISMATCH`, `INVALID_BINDING`, `PRINCIPAL_MISMATCH`, `AGENT_MISMATCH`, `OPERATION_MISMATCH`, and `TARGET_MISMATCH`. Gate denial retains its reason, including `AUTHORITY_REVOKED`. The tool response records `decision_source` as `BINDING` or `GATE` and compares the Gate result with the actual endpoint count. A missing or inconsistent state transition cannot report successful execution.

**Trust boundary:** the test harness controls session registration and presents a session handle to the adapter. This is simulated identity only. A real integration would need an independently trusted authentication layer to supply a non-forgeable identity context and prevent callers from registering or borrowing another session. The adapter-local binding does not add a user field to the Phase 0 grant. Direct callers of the Phase 0 Gate can still provide the grant's principal string; the Gate cannot authenticate that string.

## Direct endpoint access

The endpoint's private `_commit` method rejects an arbitrary capability object. A test harness with Python-private access can read `endpoint._gate_key` and call `endpoint._commit` directly, changing endpoint state without the Gate. The included test demonstrates this on an isolated in-memory chain. That is an architectural limitation of same-process Python code, and a genuine bypass if hostile code can run in the process. It is not a bypass through the supported adapter. Process isolation or an external enforcement boundary would be needed for a stronger security claim.

## Verify

Python 3.12+ and the standard library suffice. No paid API, real identity, customer system, or device is involved.

```bash
python3 -m unittest tests.test_chain -v
python3 mutation_check.py
python3 -m unittest tests.test_phase1a -v
python3 phase1a_mutation_check.py
python3 -m unittest tests.test_phase1a1 -v
python3 phase1a1_mutation_check.py
python3 -m boundary_proof --verify examples/reference-evidence.json
python3 -m agent_tool_adapter --verify examples/phase1a-reference-evidence.json
python3 -m agent_tool_adapter.identity_evidence --verify examples/phase1a1-reference-evidence.json
```

The six Phase 1A.1 mutants remove the principal, agent, operation, target, caller-claim, and continuation-identity checks, each in a disposable scratch copy. `examples/phase1a1-mutation-results.json` records the detecting test and assertion for each. To regenerate the identity evidence without overwriting the reviewed example, run `python3 -m agent_tool_adapter.identity_evidence --output /tmp/phase1a1-evidence.json` and verify that path with `--verify`.

The canonical example records grant and request scope, simulated identity and trust level, authorization source and reason, endpoint counts, execution result, and event order. Its SHA-256 digest is a local integrity check, not independently authenticated provenance.

**Recommendation:** the simulated binding checks meet the local test contract. Actual identity assurance and protection against hostile same-process callers need validation at a real trust boundary before this design can support a production security claim.
