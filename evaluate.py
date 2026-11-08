"""Run the complete local evaluation without changing reviewed evidence files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
MUTATIONS = (
    ("mutation_check.py", "mutation-results.json"),
    ("phase1a_mutation_check.py", "phase1a-mutation-results.json"),
    ("phase1a1_mutation_check.py", "phase1a1-mutation-results.json"),
    ("phase1a2_mutation_check.py", "phase1a2-mutation-results.json"),
)
EVIDENCE = (
    ("boundary_proof", "reference-evidence.json"),
    ("agent_tool_adapter", "phase1a-reference-evidence.json"),
    ("agent_tool_adapter.identity_evidence", "phase1a1-reference-evidence.json"),
    ("process_isolation.evidence", "phase1a2-reference-evidence.json"),
)


def run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess:
    completed = subprocess.run([sys.executable, *arguments], cwd=cwd, env=environment,
                               capture_output=True, text=True, timeout=90, check=False)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(arguments)} failed ({completed.returncode}):\n"
                           f"{completed.stdout}{completed.stderr}")
    return completed


def main() -> int:
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or later is required")
    if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("the process experiment requires POSIX Unix sockets")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = run(["-m", "unittest", "discover", "-s", "tests", "-v"], ROOT, environment)
    output = result.stdout + result.stderr
    match = re.search(r"^Ran (\d+) tests? in ", output, flags=re.MULTILINE)
    if match is None or not re.search(r"^OK(?: \(|$)", output, flags=re.MULTILINE):
        raise RuntimeError(f"test summary missing or unsuccessful:\n{output}")
    test_count = int(match.group(1))
    skipped = sum(1 for line in output.splitlines() if " ... skipped " in line)
    if skipped:
        raise RuntimeError(f"{skipped} tests were skipped; complete reproduction requires zero skips")

    with tempfile.TemporaryDirectory(prefix="kimura-external-eval-") as temporary:
        scratch = Path(temporary)
        mutant_root = scratch / "mutation-workspace"
        mutant_root.mkdir()
        for package in ("boundary_proof", "agent_tool_adapter", "process_isolation", "tests"):
            shutil.copytree(ROOT / package, mutant_root / package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (mutant_root / "examples").mkdir()
        for script, _ in MUTATIONS:
            shutil.copy2(ROOT / script, mutant_root / script)

        mutation_count = 0
        for script, filename in MUTATIONS:
            completed = run([script], mutant_root, environment)
            report = json.loads(completed.stdout)
            cases = report["results"]
            if any(not case["detected"] or case["error_count"] != 0 for case in cases):
                raise RuntimeError(f"mutation check did not detect a fault: {script}")
            generated = (mutant_root / "examples" / filename).read_bytes()
            reviewed = (ROOT / "examples" / filename).read_bytes()
            if generated != reviewed:
                raise RuntimeError(f"mutation result differs from reviewed example: {filename}")
            mutation_count += len(cases)

        for module, filename in EVIDENCE:
            example = ROOT / "examples" / filename
            run(["-m", module, "--verify", str(example)], ROOT, environment)
            reproduction = scratch / filename
            run(["-m", module, "--output", str(reproduction)], ROOT, environment)
            if reproduction.read_bytes() != example.read_bytes():
                raise RuntimeError(f"fresh evidence differs from reviewed example: {filename}")

    print(json.dumps({"status": "PASS",
                      "tests": {"run": test_count, "passed": test_count - skipped,
                                "failed": 0, "errors": 0, "skipped": skipped},
                      "mutations_detected": mutation_count,
                      "evidence_verified_and_reproduced": len(EVIDENCE)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True),
              file=sys.stderr)
        raise SystemExit(1)
