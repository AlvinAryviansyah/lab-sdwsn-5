import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

import synth

HERE = os.path.dirname(os.path.abspath(__file__))
ML = os.path.join(HERE, "..")
sys.path.insert(0, ML)
sys.path.insert(0, HERE)

import run_bigan_fs as runner
from nslkdd_data import COLUMNS


class TestPhase1Runner(unittest.TestCase):
    def test_training_is_test_free_and_final_evaluation_is_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = os.path.join(temp, "data")
            checkpoints = os.path.join(temp, "checkpoints")
            reports = os.path.join(temp, "reports")
            os.makedirs(data_dir)
            train, _ = synth.make_df(500, seed=10, attack_fraction=0.3)
            train[COLUMNS].to_csv(os.path.join(data_dir, "KDDTrain+.txt"),
                                  index=False, header=False)
            args = Namespace(run_id="smoke", data_dir=data_dir, seeds=[1],
                             n_hidden=[1], epochs=1, hidden=16, zdim=4,
                             batch=64, lr=2e-4, d_steps=1, device="cpu")
            with patch.object(runner, "CHECKPOINT_ROOT", checkpoints), \
                    patch.object(runner, "REPORT_ROOT", reports):
                runner.train_experiment(args)
                self.assertFalse(os.path.exists(os.path.join(data_dir, "KDDTest+.txt")))
                with open(os.path.join(reports, "smoke", "training.json")) as stream:
                    train_report = json.load(stream)
                self.assertEqual(train_report["status"], "complete")
                self.assertEqual(len(train_report["per_seed_models"]), 4)
                self.assertFalse(os.path.exists(os.path.join(reports, "smoke", "final_test.json")))

                test, _ = synth.make_df(180, seed=11, attack_fraction=0.35)
                test[COLUMNS].to_csv(os.path.join(data_dir, "KDDTest+.txt"),
                                     index=False, header=False)
                test_args = Namespace(run_id="smoke", data_dir=data_dir,
                                      n_hidden=[1], device="cpu")
                runner.evaluate_test(test_args)
                with open(os.path.join(reports, "smoke", "final_test.json")) as stream:
                    result = json.load(stream)
                self.assertEqual(len(result["models"]), 4)
                self.assertTrue(all("attack_type_recall" in item["test"]
                                    for item in result["models"]))
                self.assertTrue(os.path.exists(os.path.join(reports, "smoke", "final_test.md")))


if __name__ == "__main__":
    unittest.main()