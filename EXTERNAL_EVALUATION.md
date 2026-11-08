# External developer evaluation handoff

This package is a local, synthetic reference experiment. The audit baseline was `77072185b2b9a50abb0b4977334d30ebd3951314`. A local clean clone of that baseline ran 23 tests with 23 passes, 0 failures, 0 errors, and 0 skips; detected all 15 mutants with 0 mutant errors; and verified all four canonical examples. That is local reproduction, not independent validation.

## Install and run

Requirements: CPython 3.12 or later; a Unix-like OS with `AF_UNIX` datagram socketpairs and inherited file descriptors; permission to spawn child processes and write temporary files. Extracting the archive also requires `tar`; making a local clone or building the archive requires Git. Linux with CPython 3.12.3 was tested. No `pip install`, paid API, network connection, model, device, or customer account is needed. Review the source and run it in a disposable local environment: the command executes Python and spawns child processes.

From a local archive:

```bash
mkdir -p /tmp/kimura-evaluation
tar -xzf /path/to/kimura-boundary-proof-evaluation.tar.gz -C /tmp/kimura-evaluation
cd /tmp/kimura-evaluation/kimura-boundary-proof
python3 evaluate.py
```

From a repository available on the same machine:

```bash
git clone --local --no-hardlinks /path/to/kimura-boundary-proof /tmp/kimura-evaluation-clone
cd /tmp/kimura-evaluation-clone
python3 evaluate.py
```

The command runs the full standard-library test suite, four mutation runners in a temporary source copy, verifies all four checked-in evidence examples, and generates fresh evidence in temporary files for byte comparison. It does not rewrite reviewed evidence. A successful run prints JSON with `status: PASS`, `tests: {run: 23, passed: 23, failed: 0, errors: 0, skipped: 0}`, `mutations_detected: 15`, and `evidence_verified_and_reproduced: 4`. The result depends on the code and fixtures inside the package; it is not a trusted external witness.

To create the archive locally from the staged or committed Git file set, run `python3 package_evaluation.py /tmp/kimura-boundary-proof-evaluation.tar.gz`. The archive contains only indexed regular files under one directory. It excludes `.git`, `.venv`, caches, and untracked files. The packager records a SHA-256 digest of the archive; retain that digest separately if custody matters. No remote repository or publication is involved.

## Scope and limits

- Phase 0's Gate checks current authority and holds a shared in-process lock through endpoint commitment. Its Python-private endpoint capability can be reached by hostile code in the same process.
- Phase 1A.1 binds a simulated principal and agent through a harness-owned session registry. Caller strings are checked against that registry; the registry does not authenticate a human or provide cryptographic identity proof.
- Phase 1A.2 places the service and agent in separate OS processes. The supplied agent script cannot import the protected package in its isolated launch, and its defined IPC interface cannot write endpoint state directly. The trusted harness assigns agent identity to an inherited channel. The service does not authenticate OS peer credentials per message. Same-UID hostile processes, descriptor theft, access to service memory or files, and admin-pipe abuse are outside the demonstrated boundary.
- The protected state is an in-memory counter. There is no durable storage, restart recovery, real case system, distributed atomicity, real LLM, or production deployment.
- Canonical JSON and SHA-256 detect differences against the current deterministic implementation. They do not authenticate who produced the code or evidence; a coherent local rewrite remains possible.

The tracked files contain the intended copyright attribution to Natalia Minkova, trading as Cyber Kimura. The audit found no tracked credential patterns, email addresses, home paths, third-party Python imports, or bundled virtual environment. The Apache-2.0 `LICENSE` matches the system's standard license text. The local provenance review found no reused external implementation, but the pre-commit authorship of the original files cannot be independently proved from this repository. These findings are a technical inventory, not a legal opinion or external IP clearance.
