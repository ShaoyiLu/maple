import unittest

import app


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = app.build_model()

    def test_new_backfill_changes_top_three(self):
        self.assertEqual([x["vehicle"] for x in self.model["top3"]], ["V-108", "V-137", "V-151"])

    def test_export_deduplicates_event_signatures(self):
        metrics = self.model["metrics"]
        self.assertEqual(metrics["raw_alerts"], 2380)
        self.assertEqual(metrics["unique_events"], 2246)
        self.assertEqual(metrics["duplicate_extras"], 134)
        self.assertEqual(metrics["backfill_alerts"], 10)

    def test_known_noise_is_identified(self):
        metrics = self.model["metrics"]
        self.assertEqual(metrics["night_noise"], 23)
        self.assertEqual(metrics["future_maintenance"], 24)

    def test_vendor_severity_is_not_trusted_blindly(self):
        self.assertEqual(self.model["metrics"]["severity_mismatch"], 37)
        first = self.model["top3"][0]
        self.assertEqual(first["vehicle"], "V-108")
        self.assertIn("P0524", " ".join(first["evidence"]))

    def test_v108_contains_both_hidden_critical_faults(self):
        first = self.model["top3"][0]
        evidence = " ".join(first["evidence"])
        self.assertIn("P0217", evidence)
        self.assertIn("P0524", evidence)
        self.assertIn("6:47 p.m.", evidence)

    def test_v137_is_still_prioritized_after_repair(self):
        v137 = next(item for item in self.model["actions"] if item["vehicle"] == "V-137")
        self.assertIn("after the vehicle was cleared", v137["why"])
        self.assertIn("6 h 52 min", " ".join(v137["evidence"]))

    def test_v151_combines_fault_and_overdue_service(self):
        v151 = next(item for item in self.model["actions"] if item["vehicle"] == "V-151")
        evidence = " ".join(v151["evidence"])
        self.assertIn("P0300", evidence)
        self.assertIn("2,350 km overdue", evidence)

    def test_v158_remains_visible_but_drops_to_fourth(self):
        vehicles = [item["vehicle"] for item in self.model["actions"]]
        self.assertEqual(vehicles[3], "V-158")
        v158 = next(item for item in self.model["actions"] if item["vehicle"] == "V-158")
        self.assertEqual(v158["status"], "In progress")

    def test_queue_is_capped_unique_and_sorted(self):
        queue = self.model["actions"]
        self.assertLessEqual(len(queue), 10)
        self.assertEqual(len(queue), len({item["vehicle"] for item in queue}))
        self.assertEqual([item["score"] for item in queue], sorted((item["score"] for item in queue), reverse=True))

    def test_every_action_has_evidence_and_next_step(self):
        for item in self.model["actions"]:
            self.assertTrue(item["evidence"], item["vehicle"])
            self.assertTrue(item["next_action"], item["vehicle"])

    def test_backfill_increases_delayed_count(self):
        metrics = self.model["metrics"]
        self.assertEqual(metrics["delayed_1h"], 127)
        self.assertEqual(metrics["delayed_24h"], 19)

    def test_driver_rates_are_normalized(self):
        d17 = next(row for row in self.model["drivers"] if row["driver"] == "D-17")
        self.assertEqual(d17["events"], 81)
        self.assertAlmostEqual(d17["rate"], 22.2, places=1)

    def test_d17_is_not_highest_normalized_driver(self):
        self.assertNotEqual(self.model["drivers"][0]["driver"], "D-17")

    def test_dashboard_renders_new_information(self):
        html = app.render_dashboard()
        self.assertIn("New information changed the ranking", html)
        self.assertIn("V-108", html)
        self.assertNotIn("__DATA__", html)


if __name__ == "__main__":
    unittest.main()
