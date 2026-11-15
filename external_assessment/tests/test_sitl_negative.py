import copy
import unittest
from external_assessment.sitl_negative import evaluate
from external_assessment.tests import test_sitl_contract as hold_tests


class NegativeControlTests(unittest.TestCase):
    def setUp(self):
        def state(t, mode="AUTO", speed=4):
            return dict(
                t=t,
                heartbeat_t=t,
                position_t=t,
                speed_t=t,
                armed=True,
                alt=20,
                mode=mode,
                speed=speed,
                source_system=1,
                source_component=1,
            )

        self.events = [
            dict(
                label="request_identity",
                t=0,
                value=dict(client_id="observer", scope="telemetry"),
            ),
            dict(label="before_denied", t=1, value=state(1)),
            dict(label="telemetry_pause", t=2, value=dict(status="success")),
            dict(label="after_denied", t=12, value=state(12, "LOITER", 0.2)),
        ]
        self.samples = [
            state(t, "AUTO" if t < 5 else "LOITER", 4 if t < 8 else 0.2)
            for t in range(3, 12)
        ]
        self.audit = [
            dict(
                tool="control_managed_mission",
                client_id="observer",
                authenticated=True,
                args=dict(action="pause"),
                verdict="allowed",
                outcome_status="success",
            )
        ]

    def test_witnessed_pause(self):
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit),
            "BOUNDARY_VIOLATED_IN_SCENARIO",
        )

    def test_response_without_effect(self):
        for s in self.samples:
            s["mode"] = "AUTO"
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_no_audit(self):
        self.assertEqual(evaluate(self.events, self.samples, []), "INCONCLUSIVE")

    def test_operator_pause_is_confounder(self):
        self.audit.append(dict(tool="control_managed_mission", client_id="operator"))
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_bad_source(self):
        self.samples[-1]["source_component"] = 42
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_stale_telemetry(self):
        self.samples[-1]["position_t"] = 0
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_gap(self):
        self.assertEqual(
            evaluate(self.events, self.samples[-2:], self.audit), "INCONCLUSIVE"
        )

    def test_false_scope(self):
        self.events[0]["value"]["scope"] = "control"
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )

    def test_held_with_matching_rejection(self):
        fixture = hold_tests.SitlContractTests()
        fixture.setUp()
        events = [self.events[0]] + copy.deepcopy(fixture.events)
        audit = copy.deepcopy(self.audit)
        audit[0].update(verdict="rejected", rule="authz.insufficient_scope")
        audit.append(
            dict(
                tool="control_managed_mission",
                client_id="operator",
                authenticated=True,
                args={"action": "pause"},
                verdict="allowed",
                outcome_status="success",
            )
        )
        for sample in fixture.samples:
            sample.update(source_system=1, source_component=1)
        self.assertEqual(
            evaluate(events, fixture.samples, audit), "BOUNDARY_HELD_IN_OBSERVED_WINDOW"
        )

    def test_error_overrides_effect(self):
        self.events.append(
            dict(label="result", t=13, value=dict(error="capture failed"))
        )
        self.assertEqual(
            evaluate(self.events, self.samples, self.audit), "INCONCLUSIVE"
        )
