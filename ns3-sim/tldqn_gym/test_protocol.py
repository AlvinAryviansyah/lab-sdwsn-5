import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import protocol


class TestGymProtocol(unittest.TestCase):
    def observation(self, phase=0):
        values = np.zeros(protocol.OBSERVATION_SIZE, dtype=np.float32)
        values[:4] = [protocol.VERSION, phase, 100, 4]
        return values

    def test_initial_and_reroute_observations(self):
        initial = protocol.parse_observation(self.observation())
        self.assertEqual((initial["nodes"], initial["seed"], initial["isolated"]), (100, 4, []))
        values = self.observation(1)
        values[4 + 25] = 1
        self.assertEqual(protocol.parse_observation(values)["isolated"], [25])
        values[1] = 0
        with self.assertRaises(ValueError):
            protocol.parse_observation(values)

    def test_invalid_observations_rejected(self):
        for field, value in ((0, 2), (1, 3), (2, 101), (3, 0), (4, 2)):
            values = self.observation()
            values[field] = value
            with self.assertRaises(ValueError):
                protocol.parse_observation(values)
        with self.assertRaises(ValueError):
            protocol.parse_observation([1, 0])

    def test_live_observation_decodes_measurements_and_unknown_sentinel(self):
        live = np.full(protocol.LIVE_OBSERVATION_SIZE, -1.0, dtype=np.float32)
        live[:4] = [2, 1, 100, 4]
        live[4:104] = 0
        live[104:204] = 0.75
        live[204:304] = 0.5
        live_request = protocol.parse_observation(live)
        self.assertEqual(live_request["phase"], 1)
        self.assertAlmostEqual(float(live_request["live_state"]["energy"][0]), 0.75)
        self.assertAlmostEqual(float(live_request["live_state"]["trust"][0]), 0.5)
        self.assertEqual(float(live_request["live_state"]["link_quality"][0]), -1.0)
        self.assertEqual(float(live_request["live_state"]["stability"][0]), -1.0)
        live[304] = 1.5
        with self.assertRaisesRegex(ValueError, "live link quality"):
            protocol.parse_observation(live)

    def test_route_message_is_label_free_and_validated(self):
        request = protocol.parse_observation(self.observation())
        row = {"node_id": 0, "dest_sink": 1, "next_hop": 1, "next_hop_is_sink": 1,
               "slot": 0, "n_candidates": 1, "own_dest": 1, "q_value": 0.25}
        action = protocol.encode_routes([row], request)
        self.assertEqual(action.shape, (protocol.ACTION_SIZE,))
        self.assertEqual(action[:3].tolist(), [1.0, 0.0, 1.0])
        self.assertEqual(action[3:11].tolist(), [0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.25])
        with self.assertRaises(ValueError):
            protocol.encode_routes([dict(row, node_malicious=1)], request)
        with self.assertRaises(ValueError):
            protocol.encode_routes([row, row], request)
        with self.assertRaises(ValueError):
            protocol.encode_routes([dict(row, q_value=float("nan"))], request)


if __name__ == "__main__":
    unittest.main()