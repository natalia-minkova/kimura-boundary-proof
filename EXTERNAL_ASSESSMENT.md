# External assessment: first bounded adapter

This optional module evaluates an external target; it does not put Kimura's Gate in front of the target. Existing reference enforcement and evidence profiles are unchanged.

Supported contract: DroneServer telemetry clients cannot request mission pause; control clients can. The adapter uses the real registered tool, guard and runner request flag with a synthetic running mission. The default in-process adapter uses no HTTP. Neither adapter uses a vehicle, LLM or background flight monitor. It is not a generic auditor or a production integration.

## Run

Use a clean DroneServer checkout at `06b7d1a6a967553f1f8c025bb6b1fc79d346fd53`, with `uv sync --frozen --group dev`. Its dependencies are optional and are not added to Kimura's core. Run the adapter in a disposable subprocess using that checkout's Python. Replace absolute paths below:

```bash
PYTHONPATH=/path/to/kimura /path/to/droneserver/.venv/bin/python -m external_assessment.droneserver --target-checkout /path/to/droneserver --output /tmp/external-held.json
PYTHONPATH=/path/to/kimura /path/to/droneserver/.venv/bin/python -m external_assessment.droneserver --target-checkout /path/to/droneserver --output /tmp/external-disabled.json --disable-auth-control
python -m external_assessment --verify /tmp/external-held.json
python -m external_assessment --verify /tmp/external-disabled.json
python -m unittest discover -s external_assessment/tests -v
python evaluate.py
```

Outputs must be fresh paths. The adapter checks that the imported DroneServer belongs to the specified checkout and tracked files are clean; it records the commit. Other commits are not validated by this work. No target tracked files are edited. The sensitivity control disables only target authentication in this fake-mission subprocess; it is not an exploit.

## Verdict and evidence

`BOUNDARY_HELD`: valid control changes the observed flag, and the forbidden request is rejected with the expected rule and no observed effect. `BOUNDARY_VIOLATED`: the forbidden request changes the flag. `INCONCLUSIVE`: the observation does not establish either outcome, including a failed positive control. Malformed observations are rejected.

The verifier validates the fixed evidence schema, hash and consistency of the verdict with observations. It never reruns DroneServer. Its exit code describes evidence validity, NOT whether the boundary held: valid evidence of a violation also exits zero. Local coherent forgery remains possible. This does not authenticate target provenance, observer identity or reported settings independently.

The observer is separate from the returned tool response but runs in the same trusted harness process. It reads `_pause_requested`, which is a request flag, not vehicle motion. State resets and settings are harness-controlled. The optional HTTP/SSE path is described below; physical integration remains future work.

## HTTP/SSE adapter

Add `--transport http-sse` to either adapter command above. This starts the actual DroneServer SSE application under uvicorn on an ephemeral loopback TCP socket. The MCP SDK opens two initialized client sessions, one control and one telemetry, and calls the registered tool over HTTP. Both sessions remain open; the control call precedes the telemetry call. The observer reads the runner flag directly rather than trusting the tool response. A controlled reset separates the two observations.

Aircraft startup is replaced with a no-op lifespan. The mission record remains synthetic and the background mission monitor does not run. This does not test streamable-HTTP, TLS, proxies, session identifier swapping, concurrent tool execution, or real vehicle effects. Client HTTP uses `trust_env=False` so loopback requests do not inherit remote proxy settings. Server and sessions shut down on completion or error.

Evidence uses adapter `http-sse-loopback/1` and transport-specific limitations. Old `registered-tool-in-process/1` evidence remains valid. The core verifier still has no DroneServer, MCP or HTTP dependencies. Its integrity checks cannot prevent a coherent forgery of observations and metadata.

Checked results for this revision: 19 external unit tests pass; protected HTTP assessment gives `BOUNDARY_HELD`; authentication-disabled HTTP sensitivity control gives `BOUNDARY_VIOLATED`. Both evidence files verify. This does not identify a vulnerability in the protected target.

## Failure handling and CI

The adapter CLI exits 2 with `assessment_completed: false` and no boundary verdict on incomplete execution (including timeout, transport failure, or invalid response). These failures do not produce evidence. Existing output files are refused. MCP errors are not counted as authorization denials. Contradictory positive-control responses produce `INCONCLUSIVE`. Evidence verification exit codes retain their separate integrity meaning.

GitHub Actions runs `evaluate.py`, the external standard-library tests, and verification of both recorded HTTP evidence files. The external tests include injected timeout/connection failures, response parsing, and server-startup cleanup. CI does not install DroneServer or execute a live HTTP assessment; the paired HTTP runs are separately reproduced locally. The workflow is read-only and uses pinned action commits.

## Separate SITL profile

[SITL_ASSESSMENT.md](SITL_ASSESSMENT.md) adds an optional real simulator process,
background mission runner and separate MAVLink observation. It has a distinct
paired verdict profile and an injected authorization-failure control. It does
not change or expand what the HTTP-only examples above establish. The combined
external suite now has 53 tests; CI also re-evaluates both recorded SITL examples.
