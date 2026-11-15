import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SitlVerifierTests(unittest.TestCase):
    def check(self, path, expected):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "external_assessment.sitl_negative",
                "--verify",
                str(path),
                "--expect",
                expected,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_saved_pair(self):
        for name, expected in [
            ("protected", "BOUNDARY_HELD_IN_OBSERVED_WINDOW"),
            ("mutated", "BOUNDARY_VIOLATED_IN_SCENARIO"),
        ]:
            with self.subTest(name=name):
                result = self.check(
                    ROOT / "external_assessment/examples/sitl" / name, expected
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_expectation(self):
        result = self.check(
            ROOT / "external_assessment/examples/sitl/mutated",
            "BOUNDARY_HELD_IN_OBSERVED_WINDOW",
        )
        self.assertEqual(result.returncode, 1)

    def test_changed_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "run"
            shutil.copytree(ROOT / "external_assessment/examples/sitl/mutated", target)
            with (target / "events.jsonl").open("a") as stream:
                stream.write("\n")
            result = self.check(target, "BOUNDARY_VIOLATED_IN_SCENARIO")
            self.assertNotEqual(result.returncode, 0)

    def test_forged_recorded_verdict_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "run"
            shutil.copytree(ROOT / "external_assessment/examples/sitl/mutated", target)
            path = target / "kimura-verdict.json"
            record = json.loads(path.read_text())
            record["verdict"] = "BOUNDARY_HELD_IN_OBSERVED_WINDOW"
            path.write_text(json.dumps(record))
            result = self.check(target, "BOUNDARY_VIOLATED_IN_SCENARIO")
            self.assertEqual(result.returncode, 1)

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.check(Path(temp), "BOUNDARY_VIOLATED_IN_SCENARIO")
            self.assertEqual(result.returncode, 2)

    def test_collection_error_rejects_conclusive_record(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "run"
            shutil.copytree(
                ROOT / "external_assessment/examples/sitl/protected", target
            )
            path = target / "kimura-verdict.json"
            record = json.loads(path.read_text())
            record["collection_error"] = "observer failed"
            path.write_text(json.dumps(record))
            self.assertEqual(
                self.check(target, "BOUNDARY_HELD_IN_OBSERVED_WINDOW").returncode, 1
            )

    def test_low_rc_is_rejected_before_startup(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "external_assessment.sitl_run",
                "--target-checkout",
                "/unused",
                "--sitl-assets",
                "/unused",
                "--run-directory",
                "/unused",
                "--rc3",
                "1000",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
