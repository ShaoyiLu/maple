import unittest

import app


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = app.build_model()

    def test_top_three_are_stable_and_actionable(self):
        self.assertEqual([x["vehicle"] for x in self.model["top3"]], ["V-137", "V-151", "V-158"])

    def test_export_deduplicates_event_signatures(self):
        metrics = self.model["metrics"]
        self.assertEqual(metrics["raw_alerts"], 2370)
        self.assertEqual(metrics["unique_events"], 2236)
        self.assertEqual(metrics["duplicate_extras"], 134)

    def test_known_noise_is_identified(self):
        metrics = self.model["metrics"]
        self.assertEqual(metrics["night_noise"], 23)
        self.assertEqual(metrics["future_maintenance"], 24)

    def test_vendor_severity_is_not_trusted_blindly(self):
        self.assertEqual(self.model["metrics"]["severity_mismatch"], 35)
        first = self.model["top3"][0]
        self.assertEqual(first["vehicle"], "V-137")
        self.assertIn("P0524", " ".join(first["evidence"]))

    def test_driver_rates_are_normalized(self):
        d17 = next(row for row in self.model["drivers"] if row["driver"] == "D-17")
        self.assertEqual(d17["events"], 81)
        self.assertAlmostEqual(d17["rate"], 22.2, places=1)


if __name__ == "__main__":
    unittest.main()
