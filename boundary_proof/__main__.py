"""Generate or verify the deterministic local Phase 0 evidence example."""
import argparse
import json
import os
from pathlib import Path

from .chain import canonical, run_reference_scenario, verify_evidence


def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.output:
        evidence = run_reference_scenario()
        if not verify_evidence(evidence):
            raise ValueError('generated evidence did not verify')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as stream:
            stream.write(canonical(evidence) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({'status': 'PASS', 'path': str(args.output),
                          'sha256': evidence['evidence_sha256']}, sort_keys=True))
        return 0
    raw = args.verify.read_bytes()
    evidence = json.loads(raw, object_pairs_hook=unique_keys)
    valid = raw == canonical(evidence) + b'\n' and verify_evidence(evidence)
    print(json.dumps({'status': 'PASS' if valid else 'INCONCLUSIVE',
                      'path': str(args.verify)}, sort_keys=True))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
