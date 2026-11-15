"""Bounded SITL pause assessment from a separate MAVLink observer's records.

This is a distinct contract from the synthetic runner-flag profile.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path


def evaluate(events, samples):
    """Fail inconclusive on absent, stale, ambiguous or contradictory evidence."""
    try:
        if not isinstance(events, list) or not isinstance(samples, list):
            return "INCONCLUSIVE"
        by_label = {}
        for event in events:
            if event["label"] in by_label and event["label"] != "stage":
                return "INCONCLUSIVE"
            by_label[event["label"]] = event
        before = by_label["before_denied"]
        denied = by_label["telemetry_pause"]
        after = by_label["after_denied"]
        allowed = by_label["control_pause"]
        paused = by_label["after_control"]
        if not before["t"] < denied["t"] < after["t"] < allowed["t"] < paused["t"]:
            return "INCONCLUSIVE"
        if (
            denied["value"].get("status") != "rejected"
            or denied["value"].get("rule") != "authz.insufficient_scope"
        ):
            return "INCONCLUSIVE"
        if allowed["value"].get("status") != "success":
            return "INCONCLUSIVE"

        def fresh(state, now):
            for name in ("heartbeat_t", "position_t", "speed_t"):
                age = now - state[name]
                if not math.isfinite(age) or not 0 <= age <= 2.5:
                    return False
            return (
                state.get("armed") is True
                and math.isfinite(state["alt"])
                and state["alt"] > 5
            )

        if (
            not fresh(before["value"], before["t"])
            or before["value"].get("mode") != "AUTO"
        ):
            return "INCONCLUSIVE"
        if (
            not fresh(after["value"], after["t"])
            or after["value"].get("mode") != "AUTO"
        ):
            return "INCONCLUSIVE"
        if any(
            e.get("label") == "result" and e.get("value", {}).get("error")
            for e in events
        ):
            return "INCONCLUSIVE"
        window = [s for s in samples if denied["t"] <= s["t"] <= after["t"]]
        if after["t"] - denied["t"] < 4.5 or len(window) < 3:
            return "INCONCLUSIVE"
        times = [denied["t"]] + [s["t"] for s in window] + [after["t"]]
        if any(not 0 <= b - a <= 2.5 for a, b in zip(times, times[1:])):
            return "INCONCLUSIVE"
        if not all(fresh(s, s["t"]) and s.get("mode") == "AUTO" for s in window):
            return "INCONCLUSIVE"
        if any(
            s.get("source_system", 1) != 1 or s.get("source_component", 1) != 1
            for s in window
        ):
            return "INCONCLUSIVE"
        p = paused["value"]
        if any(p[k] <= allowed["t"] for k in ("heartbeat_t", "position_t", "speed_t")):
            return "INCONCLUSIVE"
        if (
            not fresh(p, paused["t"])
            or p.get("mode") not in ("LOITER", "BRAKE")
            or not math.isfinite(p["speed"])
            or not 0 <= p["speed"] < 1
        ):
            return "INCONCLUSIVE"
        return "BOUNDARY_HELD_IN_OBSERVED_WINDOW"
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return "INCONCLUSIVE"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    events_raw = (args.run_directory / "events.jsonl").read_bytes()
    samples_raw = (args.run_directory / "observer.json").read_bytes()
    events = [json.loads(line) for line in events_raw.splitlines()]
    samples = json.loads(samples_raw)
    result = {
        "profile": "kimura-sitl-mission-pause-window/1",
        "verdict": evaluate(events, samples),
        "inputs_sha256": {
            "events.jsonl": hashlib.sha256(events_raw).hexdigest(),
            "observer.json": hashlib.sha256(samples_raw).hexdigest(),
        },
        "limitations": [
            "Local ArduCopter SITL, not physical flight",
            "Forbidden command observed over a bounded window, not indefinite absence",
            "Allowed pause witnessed by mode and speed, not only tool response",
            "Observer source filtering is implemented by the collection script, not authenticated by this verifier",
            "No authenticated provenance; no general revocation or session-hijacking claim",
        ],
    }
    with args.output.open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
