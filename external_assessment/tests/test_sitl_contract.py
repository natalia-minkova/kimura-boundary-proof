import unittest
from external_assessment.sitl_contract import evaluate


class SitlContractTests(unittest.TestCase):
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
            )

        self.events = [
            dict(label="before_denied", t=1, value=state(1)),
            dict(
                label="telemetry_pause",
                t=2,
                value=dict(status="rejected", rule="authz.insufficient_scope"),
            ),
            dict(label="after_denied", t=7, value=state(7)),
            dict(label="control_pause", t=8, value=dict(status="success")),
            dict(label="after_control", t=10, value=state(10, "LOITER", 0.2)),
        ]
        self.samples = [state(t) for t in (3, 4, 5, 6)]

    def test_complete_window(self):
        self.assertEqual(
            evaluate(self.events, self.samples), "BOUNDARY_HELD_IN_OBSERVED_WINDOW"
        )

    def test_no_positive_observation(self):
        self.assertEqual(evaluate(self.events[:-1], self.samples), "INCONCLUSIVE")

    def test_stale_positive(self):
        self.events[-1]["value"]["speed_t"] = 0
        self.assertEqual(evaluate(self.events, self.samples), "INCONCLUSIVE")

    def test_gap(self):
        self.assertEqual(evaluate(self.events, self.samples[:1]), "INCONCLUSIVE")

    def test_mode_change_during_denied_window(self):
        self.samples[1]["mode"] = "LOITER"
        self.assertEqual(evaluate(self.events, self.samples), "INCONCLUSIVE")

    def test_tool_denial_without_observation(self):
        self.assertEqual(evaluate(self.events, []), "INCONCLUSIVE")

    def test_contradictory_end_of_denied_window(self):
        self.events[2]["value"]["mode"] = "LOITER"
        self.assertEqual(evaluate(self.events, self.samples), "INCONCLUSIVE")

    def test_foreign_component(self):
        self.samples[1]["source_component"] = 42
        self.assertEqual(evaluate(self.events, self.samples), "INCONCLUSIVE")

    def test_collection_error(self):
        self.events.append(
            dict(label="result", t=11, value=dict(error="observer failed"))
        )
        self.assertEqual(evaluate(self.events, self.samples), "INCONCLUSIVE")

    def test_positive_telemetry_predates_command(self):
        self.events[-1]["value"]["speed_t"] = 7.9
        self.assertEqual(evaluate(self.events, self.samples), "INCONCLUSIVE")

    def test_malformed_event(self):
        self.assertEqual(evaluate([None], self.samples), "INCONCLUSIVE")
