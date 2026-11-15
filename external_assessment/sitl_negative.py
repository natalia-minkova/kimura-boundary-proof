"""Paired SITL evidence profile; target mutation metadata is NOT a verdict input."""

import math
from external_assessment.sitl_contract import evaluate as evaluate_hold


def evaluate(events, samples, audit):
    try:
        labels = {}
        for e in events:
            if e["label"] in labels and e["label"] != "stage":
                return "INCONCLUSIVE"
            labels[e["label"]] = e
        identity = labels["request_identity"]["value"]
        if identity != {"client_id": "observer", "scope": "telemetry"}:
            return "INCONCLUSIVE"
        calls = [
            a
            for a in audit
            if a.get("tool") == "control_managed_mission"
            and a.get("client_id") == "observer"
        ]
        if len(calls) != 1:
            return "INCONCLUSIVE"
        call = calls[0]
        if call.get("authenticated") is not True or call.get("args") != {
            "action": "pause"
        }:
            return "INCONCLUSIVE"
        # Paired evidence is stricter than the legacy hold-only profile.
        request = labels["telemetry_pause"]
        after = labels["after_denied"]
        window = [s for s in samples if request["t"] <= s["t"] <= after["t"]]
        if not window or any(
            s.get("source_system") != 1 or s.get("source_component") != 1
            for s in window
        ):
            return "INCONCLUSIVE"
        if any(
            b["t"] <= a["t"] or b["heartbeat_t"] <= a["heartbeat_t"]
            for a, b in zip(window, window[1:])
        ):
            return "INCONCLUSIVE"
        other_calls = [
            a
            for a in audit
            if a.get("tool") == "control_managed_mission"
            and a.get("client_id") != "observer"
        ]
        held = evaluate_hold(events, samples)
        if held == "BOUNDARY_HELD_IN_OBSERVED_WINDOW":
            if len(other_calls) != 1:
                return "INCONCLUSIVE"
            positive = other_calls[0]
            if not (
                positive.get("client_id") == "operator"
                and positive.get("authenticated") is True
                and positive.get("args") == {"action": "pause"}
                and positive.get("verdict") == "allowed"
                and positive.get("outcome_status") == "success"
            ):
                return "INCONCLUSIVE"
            return (
                held
                if call.get("verdict") == "rejected"
                and call.get("rule") == "authz.insufficient_scope"
                else "INCONCLUSIVE"
            )
        if any(
            e.get("value", {}).get("error") for e in events if e["label"] == "result"
        ):
            return "INCONCLUSIVE"
        # A violation requires no operator pause in the captured scenario.
        if "control_pause" in labels or any(
            a.get("tool") == "control_managed_mission"
            and a.get("client_id") != "observer"
            for a in audit
        ):
            return "INCONCLUSIVE"
        before = labels["before_denied"]
        request = labels["telemetry_pause"]
        after = labels["after_denied"]
        if not before["t"] < request["t"] < after["t"]:
            return "INCONCLUSIVE"
        if (
            request["value"].get("status") != "success"
            or call.get("verdict") != "allowed"
            or call.get("outcome_status") != "success"
        ):
            return "INCONCLUSIVE"

        def fresh(s, t):
            return (
                s.get("armed") is True
                and math.isfinite(s["alt"])
                and s["alt"] > 5
                and all(
                    math.isfinite(t - s[k]) and 0 <= t - s[k] <= 2.5
                    for k in ("heartbeat_t", "position_t", "speed_t")
                )
            )

        if before["value"].get("mode") != "AUTO" or not fresh(
            before["value"], before["t"]
        ):
            return "INCONCLUSIVE"
        window = [s for s in samples if request["t"] <= s["t"] <= after["t"]]
        if len(window) < 3 or not 5 <= after["t"] - request["t"] <= 15:
            return "INCONCLUSIVE"
        times = [request["t"]] + [s["t"] for s in window] + [after["t"]]
        if any(not 0 <= b - a <= 2.5 for a, b in zip(times, times[1:])):
            return "INCONCLUSIVE"
        if not all(
            fresh(s, s["t"])
            and s.get("source_system") == 1
            and s.get("source_component") == 1
            for s in window
        ):
            return "INCONCLUSIVE"
        if not fresh(after["value"], after["t"]) or after["value"].get("mode") not in (
            "LOITER",
            "BRAKE",
        ):
            return "INCONCLUSIVE"
        for s in window[-2:]:
            if (
                s.get("mode") not in ("LOITER", "BRAKE")
                or not math.isfinite(s["speed"])
                or not 0 <= s["speed"] < 1
            ):
                return "INCONCLUSIVE"
            if any(
                s[k] <= request["t"] for k in ("heartbeat_t", "position_t", "speed_t")
            ):
                return "INCONCLUSIVE"
        return "BOUNDARY_VIOLATED_IN_SCENARIO"
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return "INCONCLUSIVE"


def main():
    """Recompute a saved run and compare its recorded verdict and input hashes."""
    import argparse
    import hashlib
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--verify", type=Path, required=True)
    parser.add_argument(
        "--expect",
        choices=(
            "BOUNDARY_HELD_IN_OBSERVED_WINDOW",
            "BOUNDARY_VIOLATED_IN_SCENARIO",
            "INCONCLUSIVE",
        ),
    )
    args = parser.parse_args()
    try:
        raw = {
            name: (args.verify / name).read_bytes()
            for name in ("events.jsonl", "observer.json", "flight_logs/audit.jsonl")
        }
        events = [json.loads(line) for line in raw["events.jsonl"].splitlines()]
        samples = json.loads(raw["observer.json"])
        audit = [
            json.loads(line) for line in raw["flight_logs/audit.jsonl"].splitlines()
        ]
        result = evaluate(events, samples, audit)
        recorded = json.loads((args.verify / "kimura-verdict.json").read_text())
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
        valid = (
            recorded.get("profile") == "kimura-sitl-paired-pause/1"
            and recorded.get("verdict") == result
            and recorded.get("inputs_sha256") == hashes
            and not recorded.get("collection_error")
        )
        expected = args.expect is None or args.expect == result
        print(
            json.dumps(
                {
                    "evidence_valid": valid,
                    "verdict": result,
                    "expected_verdict_matches": expected,
                }
            )
        )
        return 0 if valid and expected else 1
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(json.dumps({"evidence_valid": False, "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
