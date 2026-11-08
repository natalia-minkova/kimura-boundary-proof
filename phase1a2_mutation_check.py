"""Run four process-boundary mutants in disposable source copies."""

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
KINDS = ("bypass_authorization", "trust_caller_identity",
         "remove_atomicity", "false_success")
MARKERS = (
    "revoked IPC request must be denied",
    "revoked IPC request must not mutate endpoint",
    "unauthorized direct IPC request must be denied",
    "direct IPC bypass must not change protected state",
    "revocation must not commit inside Gate check-to-commit window",
    "action must linearize before queued revocation",
    "no endpoint effect must not report success",
)


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("mutation anchor changed")
    return source.replace(old, new)


def mutate_service(source: str, kind: str) -> str:
    if kind == "bypass_authorization":
        source = replace_once(source, "from boundary_proof import ReferenceChain",
                              "from boundary_proof import Outcome, ReferenceChain")
        return replace_once(
            source,
            "outcome = self.chain.gate.execute(grant, agent, operation, target,\n"
            "                                          after_check=hook)  # LIVE_GATE_CHECK",
            "if hook is not None:\n"
            "            hook()  # MUTANT: pause outside Gate transaction\n"
            "        commit_before, commit_after = self.chain.endpoint._commit(\n"
            "            self.chain.endpoint._gate_key, grant)  # MUTANT: bypass Gate\n"
            "        outcome = Outcome(True, 'CURRENT_AUTHORITY', True, commit_before, commit_after)",
        )
    if kind == "trust_caller_identity":
        return replace_once(
            source,
            "identity = self.identities.get(channel)  # CHANNEL_IDENTITY_CHECK",
            "identity = (0, request.get('principal'), request.get('agent'))  # MUTANT: trust claims",
        )
    if kind == "false_success":
        source = replace_once(
            source,
            'status = "ALLOWED" if outcome.allowed and executed else "DENIED" if not outcome.allowed and not outcome.executed else "INCONCLUSIVE"',
            'status = "ALLOWED"  # MUTANT: false success after denial',
        )
        return replace_once(source,
                            '"authorized": outcome.allowed, "executed": executed,',
                            '"authorized": True, "executed": True,  # MUTANT')
    raise ValueError(kind)


def mutate_chain(source: str) -> str:
    source = replace_once(source, "from dataclasses import asdict, dataclass",
                          "from contextlib import nullcontext\nfrom dataclasses import asdict, dataclass")
    return replace_once(source, "with self._lock:  # ATOMIC_WINDOW",
                        "with nullcontext():  # MUTANT: atomicity removed")


def run_one(kind: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="kimura-p1a2-mutant-") as temporary:
        scratch = Path(temporary)
        for package in ("boundary_proof", "process_isolation"):
            shutil.copytree(ROOT / package, scratch / package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (scratch / "tests").mkdir()
        shutil.copy2(ROOT / "tests" / "__init__.py", scratch / "tests" / "__init__.py")
        shutil.copy2(ROOT / "tests" / "test_phase1a2.py",
                     scratch / "tests" / "test_phase1a2.py")
        target = (scratch / "boundary_proof" / "chain.py" if kind == "remove_atomicity"
                  else scratch / "process_isolation" / "service.py")
        source = target.read_text()
        target.write_text(mutate_chain(source) if kind == "remove_atomicity"
                          else mutate_service(source, kind))
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_phase1a2", "-v"],
            cwd=scratch, env=environment, capture_output=True, text=True,
            timeout=30, check=False,
        )
        output = completed.stdout + completed.stderr
        summary = re.search(r"^Ran (\d+) tests? in ", output, flags=re.MULTILINE)
        failed = re.search(r"^FAILED \(([^\n]+)\)", output, flags=re.MULTILINE)
        if summary is None or failed is None:
            raise RuntimeError(f"mutant test summary missing for {kind}: {output}")
        counts = {name: int(value) for name, value in
                  re.findall(r"(failures|errors)=(\d+)", failed.group(1))}
        failing_tests = re.findall(r"^(?:FAIL|ERROR): ([^\n]+)", output, flags=re.MULTILINE)
        failed_methods = sorted({name.split(" (")[0] for name in failing_tests})
        total = int(summary.group(1))
        return {"mutation": kind, "detected": completed.returncode != 0,
                "test_count": total, "passed_count": total - len(failed_methods),
                "failed_test_count": len(failed_methods),
                "failure_count": counts.get("failures", 0),
                "error_count": counts.get("errors", 0),
                "failed_test_methods": failed_methods,
                "assertion_markers": [marker for marker in MARKERS if marker in output]}


def main() -> int:
    results = [run_one(kind) for kind in KINDS]
    output = ROOT / "examples" / "phase1a2-mutation-results.json"
    output.write_text(json.dumps({"profile": "kimura-phase1a2-mutations-local/1",
                                  "results": results}, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(output), "results": results}, sort_keys=True))
    return 0 if all(item["detected"] and item["assertion_markers"] and
                    item["error_count"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
