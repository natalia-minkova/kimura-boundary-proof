# PR #4 review and hardening

Reviewed starting revision: db12718ef76d19e4441cb54346eb2529d60ab581.
This is a same-operator code/evidence review, not an independent audit.

## Findings addressed

| Finding | Before | After |
| --- | --- | --- |
| Missing operator audit in protected trial | Removing the positive-control audit still returned HELD | Exactly one authenticated successful operator pause is required; missing, conflicting or extra control audit gives INCONCLUSIVE |
| Missing observer source fields | Legacy hold defaults silently supplied source IDs | Paired profile requires explicit system 1/component 1 on request-window samples |
| Repeated observations | Equal observation times could count as separate samples | Sample and heartbeat times must strictly increase |
| Recorded collection error | Verifier ignored collection_error alongside a conclusive verdict | Nonempty collection_error invalidates the recorded result |
| Misleading throttle option | --rc3 1000 was accepted but the runner always sent 1500 | Only neutral 1500 is accepted, with 1500 the default |
| Teardown ordering | Observer-close or evidence-write failure could prevent child cleanup | All teardown steps are attempted; owned processes are stopped before evidence writes |

The first two issues were reproduced by removing fields/rows from copies of the
recorded protected evidence. The original complete logs were not modified.
This does not overturn their result. The missing-data cases now fail inconclusive.
Regression tests also cover a contradictory operator outcome, an additional
control client, duplicate observations, recorded collection error and low-RC
argument rejection. The cleanup regression launches a real disposable child,
injects observer.close failure, and confirms the child exits and its log closes.

## Validation and remaining limits

The full external suite has 53 tests. Both saved paired examples retain their
original computed verdicts and input digests: protected HELD; intentional mutant
VIOLATED. The hold-only legacy evaluator is retained for its historical profile;
the new stricter checks apply to the paired profile. Hashes and source IDs remain
local integrity aids, not authenticated provenance.

The live scenario itself was already exercised in the paired experiment. These
review changes were checked through offline evidence, regression tests, CLI
failure behavior and real child-process cleanup; no new simulated flight is
claimed for the hardened collector. The original manifests refer to the original
source bytes, not to this newer revision. The scalar thresholds and mission
sequence are unchanged. This remains a bounded experiment, not a production
runner: port selection is not atomic, target helpers are trusted, and early
startup/input failures may leave an incomplete evidence directory. Such output
must not be treated as a completed assessment.

No upstream vulnerability, CVE, physical safety or independent validation claim
is supported. Horizontal speed is explicitly distinct from vertical hold. The
example source IDs, disposable keys and simulated location are lab data. No
physical hardware or external deployment was used during this review.
