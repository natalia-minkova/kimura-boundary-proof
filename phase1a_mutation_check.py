"""Run three Phase 1A mutants in disposable directories only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("mutation anchor changed")
    return source.replace(old, new)


def mutate_adapter(source: str, kind: str) -> str:
    if kind == "bypass_gate":
        source = _replace_once(source, "from boundary_proof import ActionEndpoint, Gate",
                               "from boundary_proof import ActionEndpoint, Gate, Outcome")
        return _replace_once(
            source,
            "outcome = self._gate.execute(binding.grant, identity.agent_id,\n"
            "                                     request.operation, request.target)",
            "commit_before, commit_after = self._endpoint._commit(\n"
            "            self._endpoint._gate_key, binding.grant)  # MUTANT: bypass Gate\n"
            "        outcome = Outcome(True, 'CURRENT_AUTHORITY', True, commit_before, commit_after)",
        )
    if kind == "false_success_after_denial":
        return _replace_once(source,
                             'return self.status == "ALLOWED" and self.authorized and self.executed',
                             'return self.status in ("ALLOWED", "DENIED")  # MUTANT: false success')
    raise ValueError(kind)


def mutate_chain(source: str) -> str:
    source = _replace_once(source, "self._next = 1\n",
                           "self._next = 1\n"
                           "        self._cached_current = {}  # MUTANT: never invalidated\n")
    source = _replace_once(source, "self._grants[grant.grant_id] = (grant, True)\n",
                           "self._grants[grant.grant_id] = (grant, True)\n"
                           "            self._cached_current[grant.grant_id] = True  # MUTANT\n")
    return _replace_once(source, 'return self.inspect(grant) == "CURRENT"',
                         'return self._cached_current.get(grant.grant_id, False)  # MUTANT')


def run_one(kind: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="kimura-phase1a-mutant-") as temporary:
        scratch = Path(temporary)
        for package in ("boundary_proof", "agent_tool_adapter", "tests"):
            shutil.copytree(ROOT / package, scratch / package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if kind == "stale_authorization":
            target = scratch / "boundary_proof" / "chain.py"
            target.write_text(mutate_chain(target.read_text()))
        else:
            target = scratch / "agent_tool_adapter" / "adapter.py"
            target.write_text(mutate_adapter(target.read_text(), kind))
        environment = {**os.environ, "PYTHONPATH": str(scratch)}
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_phase1a", "-v"],
            cwd=scratch, env=environment, text=True, capture_output=True,
            timeout=20, check=False,
        )
        output = completed.stdout + completed.stderr
        summary = re.search(r"^Ran (\d+) tests? in ", output, flags=re.MULTILINE)
        failed = re.search(r"^FAILED \(([^\n]+)\)", output, flags=re.MULTILINE)
        if summary is None or failed is None:
            raise RuntimeError(f"test summary missing for {kind}: {output}")
        counts = {name: int(value) for name, value in
                  re.findall(r"(failures|errors)=(\d+)", failed.group(1))}
        tests = int(summary.group(1))
        failures = counts.get("failures", 0)
        errors = counts.get("errors", 0)
        failing_tests = re.findall(r"^(?:FAIL|ERROR): ([^\n]+)", output, flags=re.MULTILINE)
        failed_methods = sorted({name.split(" (")[0] for name in failing_tests})
        markers = [marker for marker in (
            "revoked workflow must be denied",
            "revoked workflow must not change actual endpoint state",
            "scope mismatch must be denied",
            "denial must not report success",
            "no effect must not report success",
            "reference evidence must pass",
        ) if marker in output]
        return {"mutation": kind, "detected": completed.returncode != 0,
                "test_count": tests, "passed_count": tests - len(failed_methods),
                "failed_test_count": len(failed_methods),
                "failure_count": failures, "error_count": errors,
                "failing_tests": failing_tests, "failed_test_methods": failed_methods,
                "assertion_markers": markers}


def main() -> int:
    results = [run_one(kind) for kind in
               ("bypass_gate", "false_success_after_denial", "stale_authorization")]
    output = ROOT / "examples" / "phase1a-mutation-results.json"
    output.write_text(json.dumps({"profile": "kimura-phase1a-mutations-local/1",
                                  "results": results}, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(output), "results": results}, sort_keys=True))
    return 0 if all(result["detected"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
