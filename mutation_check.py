"""Run two deliberately broken copies in disposable scratch directories only."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'boundary_proof' / 'chain.py'


def mutate(source: str, kind: str) -> str:
    if kind == 'stale_authorization_cache':
        old = 'self._lock = authorization._lock\n'
        new = old + '        self._cached_current = {}  # MUTANT ONLY\n'
        check = 'current = self._authorization.is_current(grant)  # LIVE_AUTHORITY_CHECK'
        replacement = ('current = self._cached_current.setdefault(\n'
                       '                    grant.grant_id, self._authorization.is_current(grant))  # MUTANT ONLY')
        if source.count(old) != 1 or source.count(check) != 1:
            raise RuntimeError('stale-cache mutation anchor changed')
        return source.replace(old, new).replace(check, replacement)
    if kind == 'remove_atomicity':
        anchor = 'with self._lock:  # ATOMIC_WINDOW'
        if source.count(anchor) != 1:
            raise RuntimeError('atomicity mutation anchor changed')
        return source.replace('from dataclasses import asdict, dataclass',
                              'from contextlib import nullcontext\nfrom dataclasses import asdict, dataclass', 1).replace(
                                  anchor, 'with nullcontext():  # MUTANT ONLY')
    raise ValueError(kind)


def run_one(kind: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix='kimura-boundary-mutant-') as temporary:
        scratch = Path(temporary)
        shutil.copytree(ROOT / 'boundary_proof', scratch / 'boundary_proof',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'tests', scratch / 'tests',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc',
                                                       'test_phase1a.py', 'test_phase1a1.py',
                                                       'test_phase1a2.py'))
        target = scratch / 'boundary_proof' / 'chain.py'
        target.write_text(mutate(SOURCE.read_text(), kind))
        environment = {**os.environ, 'PYTHONPATH': str(scratch)}
        completed = subprocess.run([sys.executable, '-m', 'unittest', 'discover',
                                    '-s', 'tests', '-v'], cwd=scratch, env=environment,
                                   capture_output=True, text=True, timeout=20, check=False)
        output = completed.stdout + completed.stderr
        failures = re.findall(r'^(?:FAIL|ERROR): ([^\n]+)', output, flags=re.MULTILINE)
        summary = re.search(r'^Ran (\d+) tests? in ', output, flags=re.MULTILINE)
        failed = re.search(r'^FAILED \(([^\n]+)\)', output, flags=re.MULTILINE)
        if summary is None or failed is None:
            raise RuntimeError(f'mutant test summary missing for {kind}')
        counts = {name: int(value) for name, value in
                  re.findall(r'(failures|errors)=(\d+)', failed.group(1))}
        test_count = int(summary.group(1))
        failure_count = counts.get('failures', 0)
        error_count = counts.get('errors', 0)
        traces = [ast.literal_eval(line.removeprefix('RACE_TRACE ')) for line in output.splitlines()
                  if line.startswith('RACE_TRACE ')]
        states = [ast.literal_eval(line.removeprefix('STATE_TRACE ')) for line in output.splitlines()
                  if line.startswith('STATE_TRACE ')]
        return {'mutation': kind, 'test_exit_code': completed.returncode,
                'detected': completed.returncode != 0,
                'test_count': test_count, 'passed_count': test_count - failure_count - error_count,
                'failure_count': failure_count, 'error_count': error_count,
                'failing_tests': failures, 'race_traces': traces, 'state_traces': states,
                'assertion_markers': [marker for marker in (
                    "'CURRENT_AUTHORITY' != 'AUTHORITY_REVOKED'",
                    'revocation must not commit inside the protected check-to-commit window',
                    'no execution may commit after revocation has committed') if marker in output]}


def main() -> int:
    results = [run_one(kind) for kind in ('stale_authorization_cache', 'remove_atomicity')]
    output = ROOT / 'examples' / 'mutation-results.json'
    output.write_text(json.dumps({'profile': 'kimura-boundary-mutations-local/1',
                                  'results': results}, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'results': results, 'output': str(output)}, sort_keys=True))
    return 0 if all(item['detected'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
