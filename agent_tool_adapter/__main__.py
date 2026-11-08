"""Generate or verify canonical Phase 1A evidence."""

import argparse
import json
from pathlib import Path

from boundary_proof.chain import canonical

from .evidence import run_reference_scenario, verify_evidence


def _unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output:
        evidence = run_reference_scenario()
        if not verify_evidence(evidence):
            raise ValueError("generated evidence did not meet the workflow contract")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(canonical(evidence) + b"\n")
        print(json.dumps({"status": "PASS", "path": str(args.output)}, sort_keys=True))
        return 0
    raw = args.verify.read_bytes()
    evidence = json.loads(raw, object_pairs_hook=_unique_keys)
    valid = raw == canonical(evidence) + b"\n" and verify_evidence(evidence)
    print(json.dumps({"status": "PASS" if valid else "INCONCLUSIVE",
                      "path": str(args.verify)}, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
