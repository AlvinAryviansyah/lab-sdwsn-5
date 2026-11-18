import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import build_dashboard as dashboard
import hybrid_ids as hybrid
import telemetry_schema as schema


class TestDashboardData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dashboard.build()

    def test_baseline_is_matching_run_without_detection(self):
        baseline = self.data["runs"]["baseline_no_ids"]["100_4"]
        root = os.path.join(dashboard.RES, "bigan_test_4_6_20261107_214507")
        metrics = schema.load_metrics(os.path.join(root, "metrics_100_s4.csv"))
        self.assertEqual(metrics["ids_mode"], 2)
        self.assertEqual(baseline["m"]["pdr_percent"], metrics["pdr_percent"])
        self.assertIsNone(baseline["det"])
        self.assertIsNone(baseline["m"]["TP"])
        self.assertFalse(self.data["configs"]["baseline_no_ids"]["dto_available"])
        hybrid_run = self.data["runs"]["hybrid_telemetry_f2"]["100_4"]
        self.assertEqual(baseline["gt"], hybrid_run["gt"])

    def test_pilot_metrics_and_telemetry_match_ns3(self):
        run = self.data["runs"]["pilot_test"]["100_4"]
        root = os.path.join(dashboard.RES, "bigan_test_replay_20261107_215011")
        metrics = schema.load_metrics(os.path.join(root, "metrics_100_s4.csv"))
        self.assertEqual(run["m"]["pdr_percent"], metrics["pdr_percent"])
        self.assertEqual(run["m"]["TP"], metrics["TP"])
        self.assertEqual(run["m"]["control_overhead_mps"], metrics["control_overhead_mps"])
        self.assertFalse(self.data["configs"]["pilot_test"]["dto_available"])
        totals = schema.node_totals(schema.load_nodes(
            os.path.join(root, "telemetry_100_s4.csv")), 100)
        self.assertEqual(run["tel"]["node"]["self_ip_orig_pkts"][4],
                         totals["self_ip_orig_pkts"][4])
        self.assertEqual(len(run["det"]), 100)
        self.assertEqual(sum(row["pred"] for row in run["det"]), 11)
        self.assertEqual(sum(run["gt"]), 10)
        self.assertEqual(run["ts"], [[8.3, 8.0, 87.0, 3.0, 2.0]])

    def test_hybrid_data_and_routing_use_selected_scenario(self):
        run = self.data["runs"]["hybrid_f2"]["100_1"]
        self.assertTrue(self.data["configs"]["hybrid_f2"]["dto_available"])
        self.assertEqual(len(run["dto"]), 100)
        self.assertEqual(run["m"]["dto_TP"], 3)
        self.assertEqual(len(run["blocked"]), int(run["m"]["nodes_blocked"]))
        self.assertTrue(all(path[0] == sensor for sensor, path in enumerate(run["paths"])))
        self.assertIn("100_6", self.data["runs"]["pilot_test"])
        self.assertNotIn("60_6", self.data["runs"]["pilot_test"])

    def test_missing_and_invalid_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "predictions.csv")
            self.assertIsNone(dashboard.decision_rows(path, 2, pilot=True))
            self.assertIsNone(dashboard.node_telemetry(directory, 2, 1))
            self.assertIsNone(dashboard.labels_from(path, 2))
            with open(path, "w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["node_id", "score", "threshold", "pred_intrusion"])
                writer.writerow([0, 0.1, 0.2, 0])
            with self.assertRaisesRegex(ValueError, "incomplete"):
                dashboard.decision_rows(path, 2, pilot=True)

    def test_partial_telemetry_does_not_require_audit_or_links(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry_dir = os.path.join(directory, "partial")
            os.makedirs(telemetry_dir)
            shutil.copyfile(os.path.join(dashboard.RES, "bigan_test_replay_20261107_215011",
                                         "telemetry_100_s4.csv"),
                            os.path.join(telemetry_dir, "telemetry_100_s4.csv"))
            with patch.object(dashboard, "S2", directory):
                result = dashboard.telemetry_view("partial", 100, 4, [])
            self.assertIsNotNone(result)
            self.assertIsNone(result["audit"])
            self.assertEqual(result["hops"], {})

    def test_hybrid_telemetry_requires_matching_f2_results(self):
        decisions = [{"node_id": "0", "dto_decision": "malicious", "bigan_pred": "1", "isolate": "1"},
                     {"node_id": "1", "dto_decision": "insufficient_evidence", "bigan_pred": "1", "isolate": "0"}]
        predictions = [{"pred": 1}, {"pred": 1}]
        metrics = {"ids_mode": 1, "hybrid_pilot_bigan": 1, "bigan_alarms": 2,
                   "nodes_blocked": 1, "TP": 1, "FP": 1, "TN": 0, "FN": 0,
                   "dto_TP": 1, "dto_FP": 0, "dto_TN": 1, "dto_FN": 0}
        dashboard.validate_telemetry_hybrid(decisions, predictions, metrics, [1, 0])
        decisions[1]["isolate"] = "1"
        with self.assertRaisesRegex(ValueError, "F2"):
            dashboard.validate_telemetry_hybrid(decisions, predictions, metrics, [1, 0])

    def test_hybrid_source_hashes_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "source.csv")
            with open(path, "w") as stream:
                stream.write("recorded data\n")
            meta = {"source_sha256": dashboard.file_sha256(path)}
            dashboard.validate_hybrid_sources(meta, {"source_sha256": path})
            with open(path, "a") as stream:
                stream.write("changed\n")
            with self.assertRaisesRegex(ValueError, "provenance mismatch"):
                dashboard.validate_hybrid_sources(meta, {"source_sha256": path})

    def test_hybrid_replay_gate_checks_snapshot_and_features(self):
        source = os.path.join(dashboard.RES, "bigan_test_4_6_20261107_214507")
        replay = os.path.join(dashboard.RES, "bigan_test_replay_20261107_215011")
        with tempfile.TemporaryDirectory() as directory:
            source_copy = os.path.join(directory, "source")
            replay_copy = os.path.join(directory, "replay")
            os.makedirs(source_copy)
            os.makedirs(replay_copy)
            for name in ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv"):
                shutil.copyfile(os.path.join(source, name), os.path.join(source_copy, name))
                shutil.copyfile(os.path.join(replay, name), os.path.join(replay_copy, name))
            self.assertIsNone(dashboard.hybrid_replay_gate(source_copy, replay_copy, 100, 4))
            for folder in (source_copy, replay_copy):
                with open(os.path.join(folder, "ids_snapshot_100_s4.csv"), "w") as stream:
                    stream.write("key,value\nt_s,8.3\nevent_count,1\n")
            self.assertTrue(dashboard.hybrid_replay_gate(source_copy, replay_copy, 100, 4))
            with open(os.path.join(replay_copy, "ids_snapshot_100_s4.csv"), "a") as stream:
                stream.write("changed,1\n")
            self.assertFalse(dashboard.hybrid_replay_gate(source_copy, replay_copy, 100, 4))

    def test_hybrid_telemetry_adapter_with_temporary_fixture(self):
        source = os.path.join(dashboard.RES, "bigan_test_4_6_20261107_214507")
        inputs = os.path.join(dashboard.RES, "bigan_pilot_test_4_6")
        original_predictions = os.path.join(
            dashboard.REP, "bigan_ns3_pilot", "pilot_20261107_211217", "predictions_test_4_6")
        with tempfile.TemporaryDirectory() as directory:
            results = os.path.join(directory, "results")
            reports = os.path.join(directory, "reports")
            input_copy = os.path.join(results, "bigan_pilot_test_4_6")
            source_copy = os.path.join(results, "bigan_test_4_6_20261107_214507")
            replay = os.path.join(results, "bigan_hybrid_f2_4_6")
            output = os.path.join(results, "bigan_hybrid_f2_decisions_4_6")
            predictions = os.path.join(reports, "bigan_ns3_pilot", "pilot_20261107_211217",
                                       "predictions_test_4_6")
            shutil.copytree(inputs, input_copy)
            os.makedirs(source_copy)
            os.makedirs(replay)
            os.makedirs(predictions)
            for name in ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv"):
                shutil.copyfile(os.path.join(source, name), os.path.join(source_copy, name))
                shutil.copyfile(os.path.join(source, name), os.path.join(replay, name))
            for folder in (source_copy, replay):
                with open(os.path.join(folder, "ids_snapshot_100_s4.csv"), "w") as stream:
                    stream.write("key,value\nt_s,8.3\nevent_count,1\n")
            telemetry = schema.paths(source_copy, 100, 4)
            with open(telemetry["meta"], "w") as stream:
                json.dump({"num_nodes": 100, "seed": 4, "sim_time_s": 10.0, "window_s": 7.3,
                           "wd_late_s": 1.0}, stream)
            prediction_path = os.path.join(predictions, "bigan_pilot_predictions_100_s4.csv")
            shutil.copyfile(os.path.join(original_predictions, os.path.basename(prediction_path)),
                            prediction_path)
            with open(prediction_path + ".meta.json", "w") as stream:
                json.dump({"nodes": 100, "seed": 4, "window": 0,
                           "contains_ground_truth": False,
                           "source_features_sha256": {key: hybrid.sha256(telemetry[key])
                                                      for key in ("node", "links")}}, stream)
            hybrid.main(["--telem-dir", source_copy, "--scenario-dir", "unused",
                         "--route-dir", os.path.join(input_copy, "routes"),
                         "--bigan-pred-dir", predictions, "--out-dir", output,
                         "--nodes", "100", "--seeds", "4", "--fusion", "F2"])
            with open(os.path.join(output, "hybrid_decisions_100_s4.csv"), newline="") as stream:
                decisions = list(csv.DictReader(stream))
            with open(os.path.join(output, "hybrid_meta.json")) as stream:
                provenance = json.load(stream)["scenarios"]["100_s4"]
            labels = dashboard.labels_from(os.path.join(input_copy, "scenarios",
                                                         "bigan_decisions_100_s4.csv"), 100)
            metrics = {"ids_mode": 1, "hybrid_pilot_bigan": 1, "windows": 1,
                       "bigan_alarms": 0, "nodes_blocked": 0,
                       "reroute_changed": len(provenance["reroute"]["changed_entries"])}
            for key in ("TP", "TN", "FP", "FN", "dto_TP", "dto_TN", "dto_FP", "dto_FN"):
                metrics[key] = 0
            for row in decisions:
                actual = bool(labels[int(row["node_id"])])
                bigan = row["bigan_pred"] == "1"
                dto = row["dto_decision"] == "malicious"
                for prefix, predicted in (("", bigan), ("dto_", dto)):
                    name = ("TP" if actual else "FP") if predicted else ("FN" if actual else "TN")
                    metrics[prefix + name] += 1
                metrics["bigan_alarms"] += int(bigan)
                metrics["nodes_blocked"] += int(row["isolate"])
            with open(os.path.join(replay, "metrics_100_s4.csv"), "w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["metric", "value"])
                writer.writerows(metrics.items())
            data = {"configs": {}, "runs": {}}
            with patch.object(dashboard, "RES", results), patch.object(dashboard, "REP", reports):
                dashboard.add_telemetry_hybrid_runs(data)
            run = data["runs"]["hybrid_telemetry_f2"]["100_4"]
            self.assertTrue(run["replay_verified"])
            self.assertEqual(len(run["dto"]), 100)
            self.assertEqual(sum(row["pred"] for row in run["det"]), 11)
            self.assertEqual(len(run["blocked"]), metrics["nodes_blocked"])

    def test_latest_tldqn_ns3gym_modes_use_verified_adaptive_runs(self):
        gym_tools = os.path.join(dashboard.ROOT, "ns3-sim", "tldqn_gym")
        if gym_tools not in sys.path:
            sys.path.insert(0, gym_tools)
        import check_parity

        names = ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv",
                 "telemetry_meta_100_s4.json", "ids_snapshot_100_s4.csv")
        integer_fields = ("node_id", "dest_sink", "next_hop", "next_hop_is_sink",
                          "slot", "n_candidates", "own_dest")

        def route_rows(path):
            with open(path, newline="") as stream:
                rows = list(csv.DictReader(stream))
            return [{**{name: int(row[name]) for name in integer_fields},
                     "q_value": float(row["q_value"])} for row in rows]

        with tempfile.TemporaryDirectory() as directory:
            runs_root = os.path.join(directory, "runs")
            control_dir = os.path.join(runs_root, "csv_control_adaptive_ns348_100_s4")
            gym_dir = os.path.join(runs_root, "tldqn_live_adaptive_100_s4")
            for run_dir in (control_dir, gym_dir):
                telemetry = os.path.join(run_dir, "telemetry")
                os.makedirs(telemetry)
                for name in names:
                    shutil.copyfile(os.path.join(check_parity.BASE_A, name),
                                    os.path.join(telemetry, name))
            control_metrics = (check_parity.BASE_A / "metrics_100_s4.csv").read_bytes()
            (Path(control_dir) / "metrics.csv").write_bytes(control_metrics)
            gym_metrics = control_metrics.replace(b"reroute_changed,0", b"reroute_changed,1")
            (Path(gym_dir) / "metrics.csv").write_bytes(gym_metrics)

            initial_routes = route_rows(check_parity.INPUTS / "tldqn_nexthop_100_s4.csv")
            live_routes = [dict(row) for row in initial_routes]
            topology = dashboard.HoneycombTopology(100)
            changed = next(row for row in live_routes
                           if row["node_id"] == 0 and row["dest_sink"] == 2)
            candidates = topology.slots(changed["node_id"], 100 + changed["dest_sink"])
            old_node = (100 + changed["next_hop"] if changed["next_hop_is_sink"]
                        else changed["next_hop"])
            new_slot = next(index for index, candidate in enumerate(candidates)
                            if candidate >= 0 and candidate != old_node)
            new_node = int(candidates[new_slot])
            changed["slot"] = new_slot
            changed["next_hop_is_sink"] = int(topology.is_sink(new_node))
            changed["next_hop"] = new_node - 100 if topology.is_sink(new_node) else new_node
            audit = {"nodes": 100, "seed": 4,
                     "checkpoint_sha256": check_parity.BASELINE_MODEL_SHA256,
                     "trust_source": "none", "requests": [
                         {"phase": 0, "routes": initial_routes},
                         {"phase": 1, "routes": live_routes, "isolated": [],
                          "stage": "live-telemetry-reroute",
                          "live_state": {"measured_links": 12, "proxy_fallback_links": 4}}]}
            with open(os.path.join(gym_dir, "audit.json"), "w", encoding="utf-8") as stream:
                json.dump(audit, stream)

            data = {"configs": {}, "runs": {}}
            dashboard.add_latest_tldqn_ns3gym_runs(data, runs_root)

        self.assertEqual(data["active_configs"], ["tldqn_csv_control", "tldqn_ns3gym_adaptive",
                                "tldqn_ns3gym_adaptive_f2"])
        self.assertEqual(set(data["runs"]["tldqn_ns3gym_adaptive"]), {"100_4"})
        gym_run = data["runs"]["tldqn_ns3gym_adaptive"]["100_4"]
        self.assertTrue(gym_run["replay_verified"], json.dumps(gym_run["same_build_parity"], indent=1))
        self.assertEqual(len(gym_run["live_route_changes"]), 1)
        self.assertIsNone(gym_run["m"]["TP"])
        self.assertTrue(data["runs"]["tldqn_csv_control"]["100_4"]["replay_verified"])
        self.assertEqual(data["configs"]["tldqn_ns3gym_adaptive"]["policy"], "TLDQN + ns3-gym")

    def test_adaptive_f2_runs_use_same_run_key_as_other_modes(self):
        # Template mencari D.runs[key][`100_${seed}`]; F2 harus memakai format yang sama.
        n, seed, tag = 100, 4, "100_s4"
        with tempfile.TemporaryDirectory() as runs_root:
            hybrid_root = os.path.join(runs_root, f"tldqn_live_hybrid_f2_{tag}")
            control_root = os.path.join(runs_root, f"tldqn_live_adaptive_{tag}")
            for folder in (os.path.join(hybrid_root, "ns3"), os.path.join(hybrid_root, "decisions"),
                           os.path.join(hybrid_root, "predictions"), os.path.join(control_root, "ns3")):
                os.makedirs(folder)
            with open(os.path.join(hybrid_root, "audit.json"), "w", encoding="utf-8") as stream:
                json.dump({"requests": [{"routes": []}, {"routes": [], "live_state": {}}]}, stream)
            with open(os.path.join(hybrid_root, "decisions", f"hybrid_decisions_{tag}.csv"), "w",
                      newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["node_id", "dto_decision", "bigan_pred", "isolate", "reason"])
                for node in range(n):
                    writer.writerow([node, "normal", 0, 0, "none"])
            with open(os.path.join(hybrid_root, "decisions", "hybrid_meta.json"), "w") as stream:
                json.dump({"scenarios": {tag: {}}}, stream)
            Path(hybrid_root, "predictions", f"bigan_pilot_predictions_{tag}.csv").write_text("")
            Path(hybrid_root, "ns3", "metrics.csv").write_text("metric,value\n")
            Path(control_root, "ns3", "metrics.csv").write_text("metric,value\n")
            data = {"configs": {}, "runs": {"tldqn_ns3gym_adaptive_f2": {}}}
            sys.path.insert(0, os.path.join(dashboard.ROOT, "ns3-sim", "tldqn_gym"))
            import check_parity
            with patch.object(check_parity, "compare", return_value={"pass": True}), \
                    patch.object(dashboard, "decision_rows", return_value=[]), \
                    patch.object(dashboard, "validate_telemetry_hybrid"), \
                    patch.object(dashboard, "validate_hybrid_sources") as sources, \
                    patch.object(dashboard, "node_telemetry", return_value=None) as telemetry:
                dashboard.add_adaptive_f2_runs(data, runs_root)
        self.assertEqual(set(data["runs"]["tldqn_ns3gym_adaptive_f2"]), {f"{n}_{seed}"})
        # Telemetry run Gym ada di <run>/ns3/telemetry: hash sumber F2 (Run A) dan
        # telemetry Mode 3 (Run B) harus dibaca dari sana.
        source_paths = sources.call_args.args[1]
        self.assertEqual(source_paths["telemetry_node_sha256"],
                         os.path.join(control_root, "ns3", "telemetry", f"telemetry_{tag}.csv"))
        self.assertEqual(telemetry.call_args.args[0],
                         os.path.join(hybrid_root, "ns3", "telemetry"))

    def test_benign_pdr_is_exported_and_nan_becomes_null(self):
        values = dashboard.metric_values({"pdr_percent": 89.8, "benign_pdr_percent": 88.4})
        self.assertEqual(values["benign_pdr_percent"], 88.4)
        values = dashboard.metric_values({"benign_pdr_percent": float("nan")})
        self.assertIsNone(values["benign_pdr_percent"])
        json.dumps(values, allow_nan=False)   # payload dashboard tidak boleh berisi NaN

    def test_template_script_only_targets_existing_elements(self):
        # $("x").innerHTML pada elemen yang tidak ada melempar TypeError di render() dan
        # membekukan navigasi menu (bug #mode-comparison-rows).
        import re
        with open(os.path.join(dashboard.HERE, "dashboard_soc_template.html"),
                  encoding="utf-8") as stream:
            html = stream.read()
        split = html.rindex("<script>")
        markup, script = html[:split], html[split:]
        used = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', script))
        defined = set(re.findall(r'id="([^"$]+)"', markup))
        self.assertEqual(sorted(used - defined), [])
        # Navigasi halaman terjadi sebelum panel di-render.
        render = script[script.index("function render(){"):]
        self.assertLess(render.index("classList.toggle('hidden'"), render.index("renderOverview("))

    def test_incomplete_seed_is_reported_not_silently_skipped(self):
        import io
        from contextlib import redirect_stderr
        with tempfile.TemporaryDirectory() as directory:
            present = os.path.join(directory, "audit.json")
            missing = os.path.join(directory, "metrics.csv")
            Path(present).write_text("{}")
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertFalse(dashboard.run_complete("Adaptive Gym", 6, (present, missing)))
                self.assertTrue(dashboard.run_complete("Adaptive Gym", 6, (present,)))
                self.assertFalse(dashboard.run_complete("Adaptive Gym", 5, (missing,)))
        report = err.getvalue()
        self.assertIn("seed 6 TIDAK LENGKAP", report)
        self.assertIn("metrics.csv", report)
        self.assertIn("seed 5 belum dijalankan", report)

    def test_latest_build_skips_archived_dashboard_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(dashboard, "TLDQN_GYM_RUNS", directory):
                data = dashboard.build(latest_only=True)
        self.assertEqual(data["active_configs"],
                         ["tldqn_csv_control", "tldqn_ns3gym_adaptive",
                          "tldqn_ns3gym_adaptive_f2"])
        self.assertEqual(set(data["configs"]), set(data["active_configs"]))
        self.assertEqual(data["runs"]["tldqn_ns3gym_adaptive"], {})
        self.assertEqual(data["runs"]["tldqn_csv_control"], {})
        self.assertEqual(data["runs"]["tldqn_ns3gym_adaptive_f2"], {})


if __name__ == "__main__":
    unittest.main()