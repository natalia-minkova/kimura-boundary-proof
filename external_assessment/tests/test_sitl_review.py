"""Regression checks using complete recorded evidence with one fact removed."""

import json
from pathlib import Path
import unittest
from external_assessment.sitl_negative import evaluate


class SitlReviewTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "examples/sitl/protected"
        self.events = [
            json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()
        ]
        self.samples = json.loads((root / "observer.json").read_text())
        self.audit = [
            json.loads(x)
            for x in (root / "flight_logs/audit.jsonl").read_text().splitlines()
        ]

    def test_missing_positive_audit(self):
        audit = [
            a
            for a in self.audit
            if not (
                a.get("tool") == "control_managed_mission"
                and a.get("client_id") == "operator"
            )
        ]
        self.assertEqual(evaluate(self.events, self.samples, audit), "INCONCLUSIVE")

    def test_missing_source_ids(self):
        for s in self.samples:
            s.pop("source_system", None)
            s.pop("source_component", None)
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_contradictory_positive_audit(self):
        for a in self.audit:
            if (
                a.get("tool") == "control_managed_mission"
                and a.get("client_id") == "operator"
            ):
                a["outcome_status"] = "failed"
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_extra_pause_client(self):
        self.audit.append(dict(tool="control_managed_mission", client_id="other"))
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_observer_close_failure_does_not_leave_child_running(self):
        import io
        import subprocess
        import sys
        import threading
        from external_assessment.sitl_run import cleanup_run

        class BrokenObserver:
            def close(self):
                raise OSError("injected observer close failure")

        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        log = io.StringIO()
        try:
            with self.assertRaisesRegex(
                RuntimeError, "injected observer close failure"
            ):
                cleanup_run(threading.Event(), None, BrokenObserver(), [child], [log])
            self.assertIsNotNone(child.poll())
            self.assertTrue(log.closed)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    def test_duplicate_observation_not_counted_as_new_sample(self):
        self.samples.insert(1, dict(self.samples[0]))
        # Duplicate a sample inside the actual request window.
        begin = next(e["t"] for e in self.events if e["label"] == "telemetry_pause")
        index = next(i for i, s in enumerate(self.samples) if s["t"] > begin)
        self.samples.insert(index, dict(self.samples[index]))
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )
