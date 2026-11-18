import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_parity
from agent import BASELINE_MODEL_SHA256
from policy import FrozenRoutingPolicy


class TestParityReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = FrozenRoutingPolicy()

    def test_detects_changed_next_hop(self):
        rows = self.policy.initial_routes(100, 4)
        path = check_parity.INPUTS / "tldqn_nexthop_100_s4.csv"
        self.assertTrue(check_parity.route_comparison(rows, path)["match"])
        altered = [dict(row) for row in rows]
        altered[0]["next_hop"] += 1
        result = check_parity.route_comparison(altered, path)
        self.assertFalse(result["match"])
        self.assertEqual(len(result["different"]), 1)

    def test_same_build_control_is_the_baseline_gate(self):
        routes = self.policy.initial_routes(100, 4)
        audit = {"nodes": 100, "seed": 4, "checkpoint_sha256": BASELINE_MODEL_SHA256,
                 "trust_source": "none", "requests": [{"phase": 0, "routes": routes}]}
        names = ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv",
                 "telemetry_meta_100_s4.json", "ids_snapshot_100_s4.csv")
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            control, gym = root / "control", root / "gym"
            for run in (control, gym):
                telemetry = run / "telemetry"
                telemetry.mkdir(parents=True)
                for name in names:
                    shutil.copyfile(check_parity.BASE_A / name, telemetry / name)
            (control / "metrics.csv").write_bytes(
                (check_parity.BASE_A / "metrics_100_s4.csv").read_bytes())
            (gym / "metrics.csv").write_bytes(
                (check_parity.BASE_A / "metrics_100_s4.csv").read_bytes())
            result = check_parity.compare(audit, gym, "baseline", control)
            self.assertTrue(result["same_build_control"]["causal_gate"]["pass"])
            self.assertTrue(result["same_build_control"][
                "metrics_identical_except_wallclock"]["identical"])
            self.assertTrue(result["pass"])

            with (gym / "metrics.csv").open(encoding="utf-8") as stream:
                changed = stream.read().replace("throughput_kbps,1857.6",
                                                "throughput_kbps,1800.0")
            (gym / "metrics.csv").write_text(changed, encoding="utf-8")
            result = check_parity.compare(audit, gym, "baseline", control)
            self.assertFalse(result["same_build_control"][
                "metrics_identical_except_wallclock"]["identical"])
            self.assertFalse(result["pass"])

    def test_adaptive_gate_requires_live_measurements_and_applied_route_count(self):
        routes = self.policy.initial_routes(100, 4)
        live_routes = [dict(row) for row in routes]
        changed = next(row for row in live_routes if not row["next_hop_is_sink"])
        changed["next_hop"] = (changed["next_hop"] + 1) % 100
        audit = {"nodes": 100, "seed": 4, "checkpoint_sha256": BASELINE_MODEL_SHA256,
                 "trust_source": "none", "requests": [
                     {"phase": 0, "routes": routes},
                     {"phase": 1, "routes": live_routes, "isolated": [],
                      "stage": "live-telemetry-reroute",
                      "live_state": {"measured_links": 12, "proxy_fallback_links": 4}}]}
        names = ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv",
                 "telemetry_meta_100_s4.json", "ids_snapshot_100_s4.csv")
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            control, gym = root / "control", root / "gym"
            for run in (control, gym):
                telemetry = run / "telemetry"
                telemetry.mkdir(parents=True)
                for name in names:
                    shutil.copyfile(check_parity.BASE_A / name, telemetry / name)
            control_metrics = (check_parity.BASE_A / "metrics_100_s4.csv").read_bytes()
            (control / "metrics.csv").write_bytes(control_metrics)
            (gym / "metrics.csv").write_bytes(
                control_metrics.replace(b"reroute_changed,0", b"reroute_changed,1"))

            result = check_parity.compare(audit, gym, "adaptive", control)
            self.assertTrue(result["pass"])
            self.assertEqual(len(result["live_route_changes"]), 1)
            self.assertTrue(result["live_action_gate"]["applied_route_count_matches"])

            audit["requests"][1]["live_state"]["measured_links"] = 0
            result = check_parity.compare(audit, gym, "adaptive", control)
            self.assertFalse(result["pass"])
            self.assertFalse(result["live_action_gate"]["live_telemetry_used"])

    def test_adaptive_hybrid_gate_checks_isolation_and_live_route_application(self):
        initial = [
            {"node_id": 0, "dest_sink": 0, "next_hop": 1,
             "next_hop_is_sink": 0, "own_dest": 1},
            {"node_id": 1, "dest_sink": 0, "next_hop": 0,
             "next_hop_is_sink": 1, "own_dest": 1},
        ]
        rerouted = [
            {"node_id": 0, "dest_sink": 0, "next_hop": 0,
             "next_hop_is_sink": 1, "own_dest": 1},
            {"node_id": 1, "dest_sink": 0, "next_hop": 0,
             "next_hop_is_sink": 1, "own_dest": 1},
        ]
        requests = [
            {"phase": 0, "routes": initial},
            {"phase": 1, "routes": rerouted, "isolated": [1],
             "stage": "live-telemetry-reroute", "live_state": {"measured_links": 3},
             "failed_entries": []},
        ]
        result = check_parity.adaptive_hybrid_route_gate(
            requests, {"reroute_changed": 1, "reroute_unresolved": 0}, [1])
        self.assertTrue(result["pass"])

    def test_adaptive_hybrid_gate_ignores_route_changes_of_isolated_sensors(self):
        # Seed 6: TLDQN juga mengubah rute milik sensor terisolasi. ApplyReroute di
        # simulator melewati sensor terisolasi (ia membuang transit), jadi perubahan
        # itu tidak dihitung di reroute_changed dan tidak boleh diharapkan gate.
        initial = [
            {"node_id": 0, "dest_sink": 0, "next_hop": 1, "next_hop_is_sink": 0, "own_dest": 1},
            {"node_id": 1, "dest_sink": 0, "next_hop": 2, "next_hop_is_sink": 0, "own_dest": 1},
            {"node_id": 2, "dest_sink": 0, "next_hop": 0, "next_hop_is_sink": 1, "own_dest": 1},
        ]
        rerouted = [
            {"node_id": 0, "dest_sink": 0, "next_hop": 2, "next_hop_is_sink": 0, "own_dest": 1},
            {"node_id": 1, "dest_sink": 0, "next_hop": 0, "next_hop_is_sink": 1, "own_dest": 1},
            {"node_id": 2, "dest_sink": 0, "next_hop": 0, "next_hop_is_sink": 1, "own_dest": 1},
        ]
        requests = [
            {"phase": 0, "routes": initial},
            {"phase": 1, "routes": rerouted, "isolated": [1],
             "stage": "live-telemetry-reroute", "live_state": {"measured_links": 3},
             "failed_entries": []},
        ]
        result = check_parity.adaptive_hybrid_route_gate(
            requests, {"reroute_changed": 1, "reroute_unresolved": 0}, [1])
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["changed_route_entries"], 1)
        self.assertEqual(result["changed_on_isolated_sensors"], 1)
        # Simulator yang (salah) ikut menerapkan perubahan sensor terisolasi -> gagal.
        result = check_parity.adaptive_hybrid_route_gate(
            requests, {"reroute_changed": 2, "reroute_unresolved": 0}, [1])
        self.assertFalse(result["pass"])

    def test_adaptive_hybrid_gate_allows_reported_unresolved_route(self):
        routes = [
            {"node_id": 0, "dest_sink": 0, "next_hop": 1,
             "next_hop_is_sink": 0, "own_dest": 1},
            {"node_id": 1, "dest_sink": 0, "next_hop": 0,
             "next_hop_is_sink": 1, "own_dest": 1},
        ]
        requests = [
            {"phase": 0, "routes": routes},
            {"phase": 1, "routes": routes, "isolated": [1],
             "stage": "live-telemetry-reroute", "live_state": {"measured_links": 3},
             "failed_entries": [{"node_id": 0, "dest_sink": 0}]},
        ]
        result = check_parity.adaptive_hybrid_route_gate(
            requests, {"reroute_changed": 0, "reroute_unresolved": 1}, [1])
        self.assertTrue(result["pass"])

    def test_adaptive_hybrid_comparison_requires_applied_f2_and_same_build_inputs(self):
        seed, nodes = 4, 100
        isolated = [3]
        initial = self.policy.initial_routes(nodes, seed)
        live_routes, route_report = self.policy.reroute(nodes, seed, isolated)
        unresolved = sum(1 for row in live_routes
                         if row["node_id"] not in isolated and
                         not row["next_hop_is_sink"] and row["next_hop"] in isolated)
        audit = {"nodes": nodes, "seed": seed,
                 "checkpoint_sha256": BASELINE_MODEL_SHA256, "trust_source": "none",
                 "requests": [
                     {"phase": 0, "routes": initial},
                     {"phase": 1, "routes": live_routes, "isolated": isolated,
                      "stage": "live-telemetry-reroute",
                      "live_state": {"measured_links": 12, "proxy_fallback_links": 4},
                      "failed_entries": route_report["failed_entries"]}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "adaptive"
            hybrid_root = root / "adaptive_hybrid"
            gym = hybrid_root / "ns3"
            decisions = hybrid_root / "decisions"
            for run in (control, gym):
                telemetry = run / "telemetry"
                telemetry.mkdir(parents=True)
                for name in ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv",
                             "telemetry_meta_100_s4.json", "ids_snapshot_100_s4.csv"):
                    shutil.copyfile(check_parity.BASE_A / name, telemetry / name)
            (control / "metrics.csv").write_bytes(
                (check_parity.BASE_A / "metrics_100_s4.csv").read_bytes())
            metrics = {"ids_mode": 1, "hybrid_pilot_bigan": 1, "nodes_blocked": 1,
                       "isolated_by_dto": 1, "isolated_by_bigan_only": 0,
                       "bigan_alarms": 1, "reroute_changed": len(route_report["changed_entries"]),
                       "reroute_unresolved": unresolved}
            with (check_parity.BASE_A / "metrics_100_s4.csv").open(newline="") as stream:
                metrics.update({row["metric"]: float(row["value"])
                                for row in csv.DictReader(stream)})
            metrics.update(ids_mode=1, hybrid_pilot_bigan=1, nodes_blocked=1,
                           isolated_by_dto=1, isolated_by_bigan_only=0, bigan_alarms=1,
                           reroute_changed=len(route_report["changed_entries"]),
                           reroute_unresolved=unresolved)
            with (gym / "metrics.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["metric", "value"])
                writer.writerows(metrics.items())
            decisions.mkdir()
            with (decisions / "hybrid_meta.json").open("w", encoding="utf-8") as stream:
                json.dump({"fusion": "F2"}, stream)
            with (decisions / "hybrid_decisions_100_s4.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["node_id", "dto_decision", "bigan_pred", "isolate", "reason"])
                for node in range(nodes):
                    writer.writerow([node, "malicious" if node in isolated else "normal",
                                     int(node == 7), int(node in isolated),
                                     "dto" if node in isolated else "none"])

            result = check_parity.compare(audit, gym, "adaptive_hybrid", control)
            self.assertTrue(result["pass"], result)
            self.assertTrue(result["f2_gate"]["isolation_matches_f2"])
            self.assertTrue(result["same_build_control"]["causal_gate"]["pass"])

    def test_complete_comparison_with_existing_metrics_as_fixture(self):
        seed = 4
        with (check_parity.DECISIONS / "hybrid_decisions_100_s4.csv").open(newline="") as stream:
            isolated = [int(row["node_id"]) for row in csv.DictReader(stream)
                        if row["isolate"] == "1"]
        reroutes, _ = self.policy.reroute(100, seed, isolated)
        audit = {"nodes": 100, "seed": seed, "checkpoint_sha256": BASELINE_MODEL_SHA256,
                 "trust_source": "none", "requests": [
                     {"phase": 0, "routes": self.policy.initial_routes(100, seed)},
                     {"phase": 1, "routes": reroutes, "isolated": isolated}]}
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            metrics = Path(directory) / "metrics.csv"
            metrics.write_bytes((check_parity.BASE_B / "metrics_100_s4.csv").read_bytes())
            result = check_parity.compare(audit, root, "hybrid")
            self.assertFalse(result["pass"])
            telemetry = root / "telemetry"
            telemetry.mkdir()
            for name in ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv",
                         "telemetry_meta_100_s4.json", "ids_snapshot_100_s4.csv"):
                shutil.copyfile(check_parity.BASE_A / name, telemetry / name)
            result = check_parity.compare(audit, root, "hybrid")
            self.assertTrue(result["initial_routes"]["match"])
            self.assertTrue(result["reroute"]["match"])
            self.assertTrue(result["causal_gate"]["pass"])
            self.assertTrue(result["pass"])
            self.assertEqual(result["metrics"]["pdr_percent"]["difference"], 0)
            control = root / "control"
            control.mkdir()
            control_telemetry = control / "telemetry"
            control_telemetry.mkdir()
            shutil.copyfile(metrics, control / "metrics.csv")
            for name in ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv",
                         "telemetry_meta_100_s4.json", "ids_snapshot_100_s4.csv"):
                shutil.copyfile(telemetry / name, control_telemetry / name)
            result = check_parity.compare(audit, root, "hybrid", control)
            self.assertTrue(result["same_build_control"]["causal_gate"]["pass"])
            self.assertTrue(result["same_build_control"][
                "metrics_identical_except_wallclock"]["identical"])
            self.assertTrue(result["pass"])
        audit["requests"][1]["isolated"] = []
        with self.assertRaisesRegex(ValueError, "isolation input"):
                check_parity.compare(audit, root, "hybrid", control)


if __name__ == "__main__":
    unittest.main()