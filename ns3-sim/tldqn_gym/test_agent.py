import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agent import run_agent
from policy import FrozenRoutingPolicy
from protocol import (ACTION_SIZE, LIVE_LINK_CELLS, LIVE_OBSERVATION_SIZE,
                      OBSERVATION_SIZE)


def observation(phase, nodes=20, seed=4, isolated=()):
    values = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
    values[:4] = [1, phase, nodes, seed]
    for node in isolated:
        values[4 + node] = 1
    return values


def live_observation(phase, nodes=20, seed=4, isolated=()):
    values = np.full(LIVE_OBSERVATION_SIZE, -1.0, dtype=np.float32)
    values[:4] = [2, phase, nodes, seed]
    values[4:104] = 0
    for node in isolated:
        values[4 + node] = 1
    values[104:204] = 0.75
    values[204:304] = 0.65
    quality_start = 304
    stability_start = quality_start + LIVE_LINK_CELLS
    values[quality_start + 1] = 0.91
    values[stability_start + 1] = 0.94
    return values


class FakeEnvironment:
    def __init__(self, observations):
        self.observations = observations
        self.actions = []

    def reset(self):
        return self.observations[0]

    def step(self, action):
        self.actions.append(action)
        next_index = len(self.actions)
        done = next_index == len(self.observations)
        return (None if done else self.observations[next_index]), 0.0, done, {}


class TestAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = FrozenRoutingPolicy()

    def test_initial_and_reroute_exchange(self):
        environment = FakeEnvironment([observation(0), observation(1, isolated=[3])])
        log = io.StringIO()
        with redirect_stdout(log):
            requests = run_agent(environment, self.policy, 20, 4, expect_reroute=True)
        self.assertEqual([request["phase"] for request in requests], [0, 1])
        self.assertEqual(requests[1]["isolated"], [3])
        self.assertTrue(all(action.shape == (ACTION_SIZE,) for action in environment.actions))
        self.assertTrue(all("node_malicious" not in row for request in requests
                            for row in request["routes"]))
        self.assertIn("phase=0 stage=flow-start", log.getvalue())
        self.assertIn("phase=1 stage=post-isolation-reroute", log.getvalue())
        self.assertEqual(log.getvalue().count("  flow node="),
                         sum(request["flow_decisions"] for request in requests))

    def test_wrong_seed_or_missing_reroute_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "seed"):
            run_agent(FakeEnvironment([observation(0, seed=5)]), self.policy, 20, 4, False)
        with self.assertRaisesRegex(ValueError, "ended"):
            run_agent(FakeEnvironment([observation(0)]), self.policy, 20, 4, True)

    def test_live_adaptive_uses_v2_telemetry_at_reroute_phase(self):
        environment = FakeEnvironment([live_observation(0), live_observation(1)])
        requests = run_agent(environment, self.policy, 20, 4, expect_reroute=True,
                             live_adaptive=True)
        self.assertEqual([request["stage"] for request in requests],
                         ["flow-start-bootstrap", "live-telemetry-reroute"])
        self.assertEqual(requests[1]["live_state"]["measured_links"], 1)
        self.assertEqual(requests[1]["live_state"]["proxy_fallback_links"], 20 * 24 - 1)
        self.assertEqual(len(environment.actions), 2)
        self.assertEqual(environment.actions[1].shape, (ACTION_SIZE,))

    def test_live_adaptive_f2_reroute_avoids_isolated_next_hops(self):
        isolated = [3]
        environment = FakeEnvironment([live_observation(0),
                                       live_observation(1, isolated=isolated)])
        requests = run_agent(environment, self.policy, 20, 4, expect_reroute=True,
                             live_adaptive=True)
        live_request = requests[1]
        self.assertEqual(live_request["isolated"], isolated)
        self.assertEqual(live_request["stage"], "live-telemetry-reroute")
        self.assertFalse(live_request["failed_entries"])
        self.assertTrue(all(int(row["next_hop_is_sink"]) or
                            row["node_id"] in isolated or row["next_hop"] not in isolated
                            for row in live_request["routes"]))


if __name__ == "__main__":
    unittest.main()