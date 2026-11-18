import csv
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ML = os.path.join(HERE, "..")
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CPP_SOURCE = os.path.join(ROOT, "ns3-sim", "honeycomb-sdwsn.cc")
sys.path.insert(0, ML)

import bigan_ns3_pilot as pilot
from telemetry_schema import LINK_COLUMNS, NODE_COLUMNS, paths


def write_trace_set(directory, n, seed):
    os.makedirs(directory, exist_ok=True)
    node_rows = []
    for node in range(n):
        row = {column: 0 for column in NODE_COLUMNS}
        row.update(node_id=node, window=0, t_start=0.0, t_end=7.3,
                   self_ip_orig_pkts=10 + node + seed % 3,
                   self_ip_orig_bytes=(10 + node + seed % 3) * (64 + node),
                   self_ip_rx_pkts=8 + node, self_ip_local_pkts=4 + node,
                   self_mac_acked=6 + node, self_mac_nacked=node % 2,
                   self_mac_drop_retry=node % 3, self_phy_tx_mpdu=12 + node,
                   self_phy_tx_bytes=(12 + node) * 90,
                   self_phy_rx_ok_mpdu=20 + node, self_phy_rx_fail_mpdu=node % 4,
                   obs_watched=3 + node % 2, obs_forwarded=2,
                   obs_unobserved_clean=1 + node % 2,
                   wd_started_as_observer=5 + node % 2)
        node_rows.append(row)
    link_rows = []
    for node in range(n):
        row = {column: 0 for column in LINK_COLUMNS}
        row.update(window=0, observer=(node + 1) % n, neighbor_type="sensor",
                   neighbor_id=node, mac_handoff_acked=3, rx_ok_from=4 + node,
                   rssi_mean_dbm=-60.0 + node, snr_mean_db=12.0 + node,
                   wd_started=3, wd_forwarded=2, wd_unobserved_clean=1,
                   wd_delay_mean_s=0.02)
        link_rows.append(row)
    locations = paths(directory, n, seed)
    for key, rows, columns in (("node", node_rows, NODE_COLUMNS),
                               ("links", link_rows, LINK_COLUMNS)):
        with open(locations[key], "w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


class TestTelemetryFeatureExtraction(unittest.TestCase):
    def test_model_matrix_log_transforms_counts_only(self):
        features = np.full(len(pilot.FEATURE_NAMES), 3.0)
        features[pilot.FEATURE_NAMES.index("observed_mean_rssi_dbm")] = -60.0
        matrix = pilot._model_matrix([{"features": features}])
        for index, name in enumerate(pilot.FEATURE_NAMES):
            expected = np.log1p(3.0) if name in pilot.LOG1P_FEATURES else features[index]
            self.assertAlmostEqual(matrix[0, index], expected, places=6)

    def test_features_use_trace_counters_and_have_no_label_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            write_trace_set(directory, 6, 1)
            records, _ = pilot.extract_window(directory, 6, 1, 0)
            self.assertEqual(len(records), 6)
            self.assertEqual(len(records[0]["features"]), len(pilot.FEATURE_NAMES))
            values = dict(zip(pilot.FEATURE_NAMES, records[0]["features"]))
            self.assertEqual(values["origin_packets"], 11.0)
            self.assertEqual(values["mean_origin_packet_bytes"], 64.0)
            self.assertEqual(values["observed_rx_ok_mpdu"], 4.0)
            self.assertEqual(values["observed_watches"], 3.0)
            self.assertFalse(any("label" in name or "malicious" in name
                                 for name in pilot.FEATURE_NAMES))
            self.assertNotIn("self_ip_fwd_pkts", pilot.FEATURE_NAMES)
            self.assertNotIn("self_ip_drop_route_error", pilot.FEATURE_NAMES)


class TestPilotInputs(unittest.TestCase):
    def test_prepared_inputs_cover_training_calibration_and_evaluation(self):
        input_dir = os.path.join(ROOT, "ns3-sim", "results", "bigan_pilot")
        for seed in (101, 102, 103, 104, 1, 2, 3):
            for subdir, prefix in (("scenarios", "bigan_decisions"),
                                   ("scenarios", "bigan_windows"),
                                   ("routes", "tldqn_nexthop")):
                self.assertTrue(os.path.isfile(os.path.join(
                    input_dir, subdir, f"{prefix}_100_s{seed}.csv")))
        labels = pilot._read_scenario_labels(os.path.join(
            input_dir, "scenarios", "bigan_decisions_100_s104.csv"), 100)
        self.assertFalse(labels.any())

    def test_calibration_seed_has_scenario_and_route(self):
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(out_dir=os.path.join(directory, "inputs"), nodes=2,
                             clean_seeds=[101], calibration_seed=104,
                             eval_seeds=[], source_scenario_dir=directory)
            with patch.object(pilot, "export_routes") as export_routes:
                pilot.prepare_inputs(args)
            scenario_dir = os.path.join(args.out_dir, "scenarios")
            for prefix in ("bigan_decisions", "bigan_windows"):
                self.assertTrue(os.path.isfile(os.path.join(
                    scenario_dir, f"{prefix}_2_s104.csv")))
            self.assertIn("104", export_routes.call_args.args[0])
            labels = pilot._read_scenario_labels(
                os.path.join(scenario_dir, "bigan_decisions_2_s104.csv"), 2)
            self.assertFalse(labels.any())


class TestAlarmOnlyPipeline(unittest.TestCase):
    def test_train_predict_and_evaluate_with_labels_separate(self):
        n = 6
        with tempfile.TemporaryDirectory() as directory:
            telem_dir = os.path.join(directory, "telemetry")
            for seed in (11, 12, 13, 14):
                write_trace_set(telem_dir, n, seed)
            self.assertEqual(pilot.verify_replay(Namespace(
                telem_a=telem_dir, telem_b=telem_dir, nodes=n, seed=14, window=0)), 0)

            checkpoint_root = os.path.join(directory, "checkpoints")
            report_root = os.path.join(directory, "reports")
            train_args = Namespace(
                run_id="smoke", telem_dir=telem_dir, nodes=n,
                train_seeds=[11, 12], calibration_seed=13, window=0,
                window_s=7.3, calibration_fpr=0.05, epochs=1, batch=8,
                hidden=8, zdim=4, lr=2e-4, seed=7, device="cpu",
                checkpoint_root=checkpoint_root, report_root=report_root)
            pilot.train_pilot(train_args)

            prediction_dir = os.path.join(directory, "predictions")
            predict_args = Namespace(run_id="smoke", telem_dir=telem_dir,
                                     nodes=n, seed=14, window=0, device="cpu",
                                     checkpoint_root=checkpoint_root,
                                     out_dir=prediction_dir)
            pilot.predict_pilot(predict_args)
            prediction_path = os.path.join(
                prediction_dir, f"bigan_pilot_predictions_{n}_s14.csv")
            with open(prediction_path, newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, pilot.PREDICTION_COLUMNS)
                prediction_rows = list(reader)
            self.assertEqual(len(prediction_rows), n)
            self.assertNotIn("actual_mal", reader.fieldnames)
            with open(prediction_path + ".meta.json") as stream:
                prediction_meta = __import__("json").load(stream)
            self.assertFalse(prediction_meta["contains_ground_truth"])
            self.assertEqual(prediction_meta["threshold_source"], "checkpoint")
            self.assertGreaterEqual(prediction_meta["model_inference_ms_per_record"], 0.0)

            predict_args.threshold = 1000000.0
            predict_args.out_dir = os.path.join(directory, "override_predictions")
            pilot.predict_pilot(predict_args)
            override_path = os.path.join(predict_args.out_dir,
                                         f"bigan_pilot_predictions_{n}_s14.csv")
            with open(override_path, newline="") as stream:
                override_rows = list(csv.DictReader(stream))
            self.assertTrue(all(float(row["threshold"]) == predict_args.threshold and
                                row["pred_intrusion"] == "0" for row in override_rows))
            with open(override_path + ".meta.json") as stream:
                override_meta = __import__("json").load(stream)
            self.assertEqual(override_meta["threshold_source"], "override")
            self.assertEqual(override_meta["threshold"], predict_args.threshold)
            predict_args.threshold = float("nan")
            with self.assertRaisesRegex(ValueError, "threshold must be finite"):
                pilot.predict_pilot(predict_args)

            scenario_dir = os.path.join(directory, "scenarios")
            os.makedirs(scenario_dir)
            source = os.path.join(scenario_dir, f"bigan_decisions_{n}_s14.csv")
            with open(source, "w", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(pilot.CPP_DECISION_COLUMNS)
                for node in range(n):
                    writer.writerow([node, int(node % 2 == 0), 0, 0, 0])

            metrics_path = os.path.join(directory, "metrics.json")
            pilot.evaluate_pilot(Namespace(run_id="smoke", pred_dir=prediction_dir,
                                           scenario_dir=scenario_dir, nodes=n,
                                           seeds=[14], out=metrics_path))
            self.assertTrue(os.path.exists(metrics_path))
            labeled_metrics_path = os.path.join(directory, "labeled_metrics.json")
            pilot.evaluate_pilot(Namespace(run_id="smoke", pred_dir=predict_args.out_dir,
                                           scenario_dir=scenario_dir, nodes=n, seeds=[14],
                                           selection_seeds=[14], out=labeled_metrics_path))
            with open(labeled_metrics_path) as stream:
                labeled_metrics = __import__("json").load(stream)
            self.assertFalse(labeled_metrics["no_threshold_or_model_selection_on_labels"])
            self.assertFalse(labeled_metrics["per_seed"][0]["labels_used_only_for_evaluation"])
            heldout_metrics_path = os.path.join(directory, "heldout_metrics.json")
            pilot.evaluate_pilot(Namespace(run_id="smoke", pred_dir=predict_args.out_dir,
                                           scenario_dir=scenario_dir, nodes=n, seeds=[14],
                                           selection_seeds=[13], out=heldout_metrics_path))
            with open(heldout_metrics_path) as stream:
                heldout_metrics = __import__("json").load(stream)
            self.assertFalse(heldout_metrics["no_threshold_or_model_selection_on_labels"])
            self.assertTrue(heldout_metrics["per_seed"][0]["labels_used_only_for_evaluation"])


class TestCppBiganAlarmContract(unittest.TestCase):
    def test_alarm_mode_loads_prediction_only_and_does_not_block(self):
        with open(CPP_SOURCE) as stream:
            source = stream.read()
        start = source.index("static void PhaseIdsBiganAlarm")
        end = source.index("// Ground truth is joined only after simulation", start)
        phase = source[start:end]
        self.assertIn('line != "node_id,score,threshold,pred_intrusion"', source)
        self.assertIn('cfg::biganDir + "/bigan_pilot_predictions_"', source)
        self.assertIn("g_biganAlarm.Get(i).pred", phase)
        self.assertNotIn("g_blocked", phase)
        self.assertNotIn("actualMal", phase)
        self.assertIn('cfg::idsSource == "bigan"', source)
        self.assertIn("automatic isolation=0", phase)
        self.assertGreater(source.index("EvaluateBiganAlarm();"),
                   source.index("Simulator::Run();"))


if __name__ == "__main__":
    unittest.main()