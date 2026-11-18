import csv
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from policy import FrozenRoutingPolicy, build_env
from protocol import LIVE_LINK_CELLS, MAX_NODES
from routing_env import EnvConfig


class TestFrozenRoutingPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = FrozenRoutingPolicy()

    def test_initial_routes_match_csv_baseline_for_each_seed(self):
        directory = ROOT / "ns3-sim/results/bigan_pilot_test_4_6/routes"
        for seed in (4, 5, 6):
            with (directory / f"tldqn_nexthop_100_s{seed}.csv").open(newline="") as stream:
                baseline = list(csv.DictReader(stream))
            generated = self.policy.initial_routes(100, seed)
            self.assertEqual(len(generated), len(baseline))
            for expected, actual in zip(baseline, generated):
                for key in ("node_id", "dest_sink", "next_hop", "next_hop_is_sink", "slot",
                            "n_candidates", "own_dest"):
                    self.assertEqual(actual[key], int(expected[key]), (seed, key, actual))
                self.assertAlmostEqual(actual["q_value"], float(expected["q_value"]), places=5)
                self.assertNotIn("node_malicious", actual)

    def test_same_seed_is_deterministic(self):
        self.assertEqual(self.policy.initial_routes(20, 4), self.policy.initial_routes(20, 4))

    def test_reroute_matches_f2_baseline_for_each_seed(self):
        directory = ROOT / "ns3-sim/results/bigan_hybrid_f2_decisions_4_6"
        for seed in (4, 5, 6):
            with (directory / f"hybrid_decisions_100_s{seed}.csv").open(newline="") as stream:
                isolated = [int(row["node_id"]) for row in csv.DictReader(stream)
                            if row["isolate"] == "1"]
            with (directory / f"reroute_nexthop_100_s{seed}.csv").open(newline="") as stream:
                baseline = list(csv.DictReader(stream))
            generated, report = self.policy.reroute(100, seed, isolated)
            self.assertEqual(len(generated), len(baseline))
            for expected, actual in zip(baseline, generated):
                for key in ("node_id", "dest_sink", "next_hop", "next_hop_is_sink", "slot",
                            "n_candidates", "own_dest"):
                    self.assertEqual(actual[key], int(expected[key]), (seed, key, actual))
                self.assertAlmostEqual(actual["q_value"], float(expected["q_value"]), places=5)
                self.assertNotIn("node_malicious", actual)
            self.assertEqual(len(report["failed_entries"]), 0)

    def test_invalid_isolation_is_rejected(self):
        for invalid in ([100], [-1], [1, 1]):
            with self.assertRaises(ValueError):
                self.policy.reroute(100, 4, invalid)

    def test_live_state_overrides_measured_features_and_keeps_proxy_fallback(self):
        nodes, seed = 20, 4
        environment = build_env(nodes, seed, np.zeros(nodes, dtype=bool),
                                EnvConfig(), trust_source="none")
        proxy_quality = float(environment.prr[0, 1])
        proxy_unmeasured_quality = float(environment.prr[0, 2])
        live_state = {"energy": np.full(MAX_NODES, 0.7, dtype=np.float32),
                      "trust": np.full(MAX_NODES, 0.8, dtype=np.float32),
                      "link_quality": np.full(LIVE_LINK_CELLS, -1.0, dtype=np.float32),
                      "stability": np.full(LIVE_LINK_CELLS, -1.0, dtype=np.float32)}
        cell = 1  # sensor 0 -> sensor 1, row-major with the protocol's fixed stride
        live_state["link_quality"][cell] = 0.91
        live_state["stability"][cell] = 0.94

        report = self.policy.apply_live_state(environment, nodes, live_state)

        self.assertAlmostEqual(float(environment.energy[0]), 0.7)
        self.assertAlmostEqual(float(environment.trust[0]), 0.8)
        self.assertAlmostEqual(float(environment.prr[0, 1]), 0.91)
        self.assertAlmostEqual(float(environment.stability[0, 1]), 0.94)
        self.assertAlmostEqual(float(environment.prr[0, 2]), proxy_unmeasured_quality)
        self.assertNotEqual(float(environment.prr[0, 1]), proxy_quality)
        self.assertEqual(report["measured_links"], 1)
        self.assertEqual(report["candidate_links"], nodes * (nodes + 4))


if __name__ == "__main__":
    unittest.main()