import csv
import json
import pathlib
import tempfile
import unittest

import netprobe


class NetprobeTests(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(netprobe.percentile([0, 10], 50), 5)
        self.assertEqual(netprobe.percentile([], 95), None)

    def test_report_classifies_outage_and_monitoring_gap_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = pathlib.Path(temporary)
            metadata = {
                "hostname": "test-host",
                "config": {"probe": {"ping_interval": 2}},
            }
            (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

            def batch(timestamp, gateway, internet):
                return {
                    "type": "ping_batch",
                    "timestamp": timestamp,
                    "results": [
                        {
                            "label": "local-gateway",
                            "address": "192.0.2.1",
                            "scope": "gateway",
                            "success": gateway,
                            "latency_ms": 1 if gateway else None,
                        },
                        {
                            "label": "vps",
                            "address": "198.51.100.10",
                            "scope": "internet",
                            "success": internet,
                            "latency_ms": 20 if internet else None,
                        },
                    ],
                }

            events = [
                batch("2026-01-01T00:00:00Z", True, True),
                batch("2026-01-01T00:00:02Z", True, False),
                batch("2026-01-01T00:00:04Z", True, False),
                batch("2026-01-01T00:00:20Z", True, True),
            ]
            (run_dir / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )

            report = netprobe.generate_report(run_dir)

            self.assertTrue(report.exists())
            with (run_dir / "outages.csv").open(newline="", encoding="utf-8") as handle:
                outages = list(csv.DictReader(handle))
            with (run_dir / "monitoring-gaps.csv").open(newline="", encoding="utf-8") as handle:
                gaps = list(csv.DictReader(handle))
            self.assertEqual(len(outages), 1)
            self.assertEqual(outages[0]["classification"], "upstream/internet (ended at monitoring gap)")
            self.assertEqual(float(outages[0]["duration_seconds"]), 2)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(float(gaps[0]["duration_seconds"]), 16)

    def test_loads_example_config(self):
        config = netprobe.load_config(pathlib.Path(netprobe.DEFAULT_CONFIG))
        self.assertGreaterEqual(len(config["ping_targets"]), 3)
        self.assertEqual(config["probe"]["iperf_port"], 5201)


if __name__ == "__main__":
    unittest.main()
