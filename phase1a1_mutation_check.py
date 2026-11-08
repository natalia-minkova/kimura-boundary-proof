"""Check identity and scope assertions against disposable adapter mutants."""

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
ANCHORS = {
    "remove_principal_check": (
        "if identity.principal_id != binding.principal_id:  # PRINCIPAL_BINDING_CHECK",
        "if False:  # MUTANT: principal check removed"),
    "remove_agent_check": (
        "if identity.agent_id != binding.agent_id:  # AGENT_BINDING_CHECK",
        "if False:  # MUTANT: agent check removed"),
    "remove_operation_check": (
        "if request.operation != binding.operation:  # OPERATION_BINDING_CHECK",
        "if False:  # MUTANT: operation check removed"),
    "remove_target_check": (
        "if request.target != binding.target:  # TARGET_BINDING_CHECK",
        "if False:  # MUTANT: target check removed"),
    "remove_claim_check": (
        "if (request.user_id != identity.principal_id or\n"
        "                request.agent_id != identity.agent_id):",
        "if False:  # MUTANT: request identity claim check removed"),
    "remove_continuation_check": (
        "if identity != workflow.started_identity:",
        "if False:  # MUTANT: continuation identity check removed"),
}
MARKERS = (
    "principal binding must reject Bob",
    "agent binding must reject Agent B",
    "operation binding must reject delete",
    "target binding must reject other case",
    "caller identity claim must not override session",
    "workflow continuation must retain identity",
)


def run_one(kind: str) -> dict[str, object]:
    old, new = ANCHORS[kind]
    with tempfile.TemporaryDirectory(prefix="kimura-phase1a1-mutant-") as temporary:
        scratch = Path(temporary)
        for package in ("boundary_proof", "agent_tool_adapter"):
            shutil.copytree(ROOT / package, scratch / package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (scratch / "tests").mkdir()
        shutil.copy2(ROOT / "tests" / "__init__.py", scratch / "tests" / "__init__.py")
        shutil.copy2(ROOT / "tests" / "test_phase1a1.py",
                     scratch / "tests" / "test_phase1a1.py")
        target = scratch / "agent_tool_adapter" / "adapter.py"
        source = target.read_text()
        if source.count(old) != 1:
            raise RuntimeError(f"mutation anchor changed: {kind}")
        target.write_text(source.replace(old, new))
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_phase1a1", "-v"],
            cwd=scratch, env={**os.environ, "PYTHONPATH": str(scratch)},
            capture_output=True, text=True, timeout=20, check=False,
        )
        output = completed.stdout + completed.stderr
        summary = re.search(r"^Ran (\d+) tests? in ", output, flags=re.MULTILINE)
        failed = re.search(r"^FAILED \(([^\n]+)\)", output, flags=re.MULTILINE)
        if summary is None or failed is None:
            raise RuntimeError(f"mutant summary missing for {kind}: {output}")
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
    results = [run_one(kind) for kind in ANCHORS]
    output = ROOT / "examples" / "phase1a1-mutation-results.json"
    output.write_text(json.dumps({"profile": "kimura-phase1a1-mutations-local/1",
                                  "results": results}, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(output), "results": results}, sort_keys=True))
    return 0 if all(item["detected"] and item["assertion_markers"] and
                    item["error_count"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
