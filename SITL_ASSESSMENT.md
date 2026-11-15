# Paired DroneServer / ArduCopter SITL assessment

This optional experiment tests one external authorization boundary: a client
configured with telemetry scope must not pause an active managed mission; a
control-scope client may pause it. Kimura observes the autopilot over a separate
MAVLink connection instead of relying on the tool response or a synthetic flag.
No model provider or physical aircraft is used.

## Recorded outcome

| Local target | Telemetry-scope pause | Observed vehicle | New verdict |
| --- | --- | --- | --- |
| Pinned, unmodified DroneServer | Rejected | AUTO during the following 10-second window | BOUNDARY_HELD_IN_OBSERVED_WINDOW |
| Disposable, narrowly mutated copy | Accepted | LOITER, horizontal speed about 0.039 m/s | BOUNDARY_VIOLATED_IN_SCENARIO |

The protected trial subsequently exercises an authorized pause. The mutated
trial sends no operator pause, so that command cannot explain the observed
transition. The same runner, firmware and parameter hashes were used in both.
Only the mutant's authorization rejection for observer/telemetry/pause is
bypassed. Other guards remain enabled. This is a sensitivity control, not a
newly discovered vulnerability in upstream DroneServer.

The earlier hold-only profile (`sitl_contract.py`) returns INCONCLUSIVE on the
mutant. The paired profile (`sitl_negative.py`) adds the witnessed-violation
rule. The collection runner does not give the target mutation label to the
verdict function. Server audit identifies the authenticated observer client;
the harness configuration binds it to telemetry scope. Neither source IDs nor
local metadata are cryptographic proof of identity or provenance.

## Offline verification — no external dependencies

From the repository root with Python 3.12+:

```sh
python -m external_assessment.sitl_negative \
  --verify external_assessment/examples/sitl/protected \
  --expect BOUNDARY_HELD_IN_OBSERVED_WINDOW
python -m external_assessment.sitl_negative \
  --verify external_assessment/examples/sitl/mutated \
  --expect BOUNDARY_VIOLATED_IN_SCENARIO
python -m unittest discover -s external_assessment/tests -v
python evaluate.py
```

The verifier recomputes the outcome and input SHA256 values, then compares them
with the recorded verdict. Exit 0 means valid evidence matching `--expect` if
provided, including when the verdict is a violation. Exit 1 means inconsistency
or expectation mismatch; exit 2 means input/read/parse failure. A coherent local
rewrite of evidence and hashes remains possible. Replaying logs is not a new
flight or independent validation.

The checked-in examples contain the unmodified JSON observations, server audit,
source/asset manifests and verdicts from the paired run. Full binary flight logs
and server logs were retained separately in `Kimura_SITL_Negative_Control.zip`.
Recorded paths, simulated coordinates and disposable LOCAL-* keys are lab data.

## Live prerequisites

Tested on Linux x86_64, Python 3.12.14. Prepare a separate target checkout and its
optional dependencies, including upstream test helpers used by this runner:

```sh
git clone https://github.com/PeterJBurke/droneserver.git droneserver
git -C droneserver checkout 06b7d1a6a967553f1f8c025bb6b1fc79d346fd53
uv sync --frozen --project droneserver
```

Create a directory containing:

- `arducopter`: https://firmware.ardupilot.org/Copter/stable-4.5.7/SITL_x86_64_linux_gnu/arducopter
- `copter.parm`: https://raw.githubusercontent.com/ArduPilot/ardupilot/Copter-4.5.7/Tools/autotest/default_params/copter.parm
- `sitl.parm`: copy `docker/ardupilot-sitl/sitl.parm` from the pinned target.

| Asset | Tested SHA256 |
| --- | --- |
| arducopter | b9035c08f003ab296b8af71f793a1dd790cd8a327f8a2e8f4aa1425953922a04 |
| copter.parm | 5e01345b45d1c6190b28bece5638bbdd4cf1cce35e05bbbf480ab24d2b51aa0e |
| sitl.parm | d4ac9d929a7e0896fe8bb74fcd4a0abf646be81ace3d1e10273547c232ed8d31 |

The binary hash and target base commit are enforced. Parameter hashes are
recorded, not enforced: use these inputs for this exact reproduction. The
simulator binary and third-party environments are not distributed here.

## Live pair

From the Kimura root, replace these absolute paths with your own. Both output
directories must be new. Run sequentially: simulator peripherals also use
default ports beyond the selected TCP ports.

```sh
/absolute/droneserver/.venv/bin/python -m external_assessment.sitl_run \
  --target-checkout /absolute/droneserver \
  --sitl-assets /absolute/assets --run-directory /absolute/new-protected \
  --base-port 19760 --rc3 1500
```

Create the mutant in a separate disposable clone at the same pinned commit.
Apply `external_assessment/fixtures/mutation.patch` there with `git apply`.
The fixture contains a deliberate authorization defect and must not be applied
to a deployment. Then run:

```sh
/absolute/droneserver/.venv/bin/python -m external_assessment.sitl_run \
  --target-checkout /absolute/droneserver-mutant \
  --sitl-assets /absolute/assets --run-directory /absolute/new-mutated \
  --base-port 20760 --rc3 1500 \
  --mutation-manifest external_assessment/fixtures/mutation.json
```

The runner accepts only a clean original target, or the manifest's exact
changed file/hash on the pinned base. The manifest is local trusted input, not
a signature. It launches its own simulator, configures loopback target access,
uses disposable keys and cleans up owned process groups. Initial port checks
are not atomic reservations; avoid concurrent use. There is no hardware-target
option. It returns 0 for either conclusive verdict and 2 for an inconclusive
assessment; preflight failures may exit nonzero without complete evidence.
Always inspect `kimura-verdict.json`, not exit 0 alone.

The recorded manifests identify the original collection source. Review hardening
adds stricter evidence validation and cleanup; those historical manifests and
logs are not rewritten to pretend they came from this newer source. The paired
scenario requires neutral throttle: `--rc3` defaults to 1500 and rejects 1000
before startup. Live collection was not repeated after these review changes;
recorded evidence, CLI rejection and process cleanup were checked separately.
See [SITL_REVIEW.md](SITL_REVIEW.md) for the review findings and validation.

## RC diagnosis and scope

Earlier runs with the simulator's low RC3 input descended after AUTO changed to
LOITER. A separate matched study observed about -5.43 m over the first three
seconds with RC3=1000 and approximately zero change with RC3=1500. Both CTUN
and SIM data supported the diagnosis. That study was retained separately in
`Kimura_SITL_Altitude_Diagnosis.zip`; it is not a third checked-in live example.
This pair explicitly uses neutral input to remove that confounder.

Horizontal speed below 1 m/s does not mean zero vertical motion. These profiles
do not establish altitude preservation or physical flight safety. An altitude
or hold-position contract must specify RC assumptions and vertical observations
separately.

Other limits: one narrow injected fault; one host/operator; approximately 1 Hz
heartbeat sampling, so brief transitions can be missed; bounded windows after
responses, not indefinite absence; no session swapping, replay, revocation,
concurrency, model-driven behavior, physical aircraft or general security proof.

CI verifies saved evidence and standard-library tests only. Live SITL remains
an optional local experiment. Original reference enforcement and its 23 tests,
15 mutation checks and four evidence examples remain unchanged.

The paired profile requires explicit source IDs on the request-window samples,
strictly increasing sample/heartbeat times, and exactly one matching successful
authenticated operator-pause audit row for the protected positive control. A
missing or contradictory positive audit is inconclusive. A recorded collection
error prevents the verifier from accepting a conclusive result. These checks
reduce accidental false conclusions; they do not prevent coherent local forgery.
