"""Compare recorded Gym routes, telemetry, decisions and simulator metrics."""

import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from agent import BASELINE_MODEL_SHA256
from hybrid_eval import determinism, identical as compare_metrics, window_rows

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "ns3-sim/results/bigan_pilot_test_4_6/routes"
DECISIONS = ROOT / "ns3-sim/results/bigan_hybrid_f2_decisions_4_6"
BASE_A = ROOT / "ns3-sim/results/bigan_test_4_6_20261107_214507"
BASE_B = ROOT / "ns3-sim/results/bigan_hybrid_f2_4_6"
FIELDS = ("node_id", "dest_sink", "next_hop", "next_hop_is_sink", "slot",
          "n_candidates", "own_dest")
NETWORK_METRICS = ("pdr_percent", "packet_drop_ratio_percent", "throughput_kbps",
                   "latency_ms", "energy_consumption_J", "benign_pdr_percent",
                   "benign_tx_packets", "benign_rx_packets", "grayhole_drops",
                   "nodes_blocked", "bigan_alarms", "reroute_changed", "reroute_unresolved")
NODE_INPUT_COLUMNS = ("node_id", "window", "self_ip_orig_pkts", "self_ip_orig_bytes",
                      "self_ip_rx_pkts", "self_ip_local_pkts", "self_mac_acked",
                      "self_mac_nacked", "self_mac_drop_retry", "self_mac_drop_other",
                      "self_mac_ack_timeout", "self_phy_tx_mpdu", "self_phy_tx_bytes",
                      "self_phy_rx_ok_mpdu", "self_phy_rx_fail_mpdu", "self_phy_rx_drop",
                      "wd_started_as_observer")
LINK_INPUT_COLUMNS = ("window", "observer", "neighbor_type", "neighbor_id",
                      "mac_handoff_acked", "mac_handoff_nacked", "mac_handoff_drop_retry",
                      "mac_handoff_drop_other", "mac_ack_timeout", "rx_ok_from",
                      "rssi_mean_dbm", "snr_mean_db", "wd_started", "wd_forwarded",
                      "wd_forwarded_late", "wd_unobserved_rxfail", "wd_unobserved_clean",
                      "wd_heard_rxfail", "wd_delay_mean_s")
CONFIG_FIELDS = ("num_nodes", "seed", "sim_time_s", "window_s", "wd_timeout_s", "wd_late_s",
                 "max_range_m", "profile", "wifi_std", "num_packets")


def route_comparison(rows, baseline_path):
    with baseline_path.open(newline="") as stream:
        baseline = list(csv.DictReader(stream))
    expected = {(int(row["node_id"]), int(row["dest_sink"])): row for row in baseline}
    actual = {(int(row["node_id"]), int(row["dest_sink"])): row for row in rows}
    if len(expected) != len(baseline) or len(actual) != len(rows):
        raise ValueError("duplicate route entries")
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    different = []
    for pair in sorted(set(expected) & set(actual)):
        old, new = expected[pair], actual[pair]
        if (any(int(old[field]) != int(new[field]) for field in FIELDS) or
                not math.isclose(float(old["q_value"]), float(new["q_value"]),
                                 rel_tol=0.0, abs_tol=5e-6)):
            different.append(list(pair))
    return {"match": not (missing or extra or different), "baseline_rows": len(baseline),
            "gym_rows": len(rows), "missing": missing, "extra": extra,
            "different": different}


def metric_comparison(baseline_path, gym_path):
    def load(path):
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        values = {row["metric"]: float(row["value"]) for row in rows}
        if len(values) != len(rows):
            raise ValueError(f"duplicate metric in {path}")
        return values

    baseline, gym = load(baseline_path), load(gym_path)
    result = {}
    for name in NETWORK_METRICS:
        old, new = baseline.get(name), gym.get(name)
        if old is None or new is None or not math.isfinite(old) or not math.isfinite(new):
            result[name] = {"baseline": None, "gym": None, "difference": None}
        else:
            result[name] = {"baseline": old, "gym": new, "difference": new - old}
    return result


def load_metrics(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    metrics = {row["metric"]: float(row["value"]) for row in rows}
    if len(metrics) != len(rows):
        raise ValueError(f"duplicate metric rows in {path}")
    return metrics


def causal_gate(gym_dir, seed, reference_dir=BASE_A):
    tag = f"100_s{seed}"
    gym_telemetry = gym_dir / "telemetry"
    reference_telemetry = reference_dir / "telemetry"
    if not reference_telemetry.is_dir():
        reference_telemetry = reference_dir
    names = (f"telemetry_{tag}.csv", f"telemetry_links_{tag}.csv",
             f"telemetry_meta_{tag}.json", f"ids_snapshot_{tag}.csv")
    if not all((directory / name).is_file()
               for directory in (reference_telemetry, gym_telemetry)
               for name in names):
        return {"pass": False, "reason": "missing run A or gym telemetry/snapshot"}
    with (reference_telemetry / names[2]).open(encoding="utf-8") as stream:
        baseline_meta = json.load(stream)
    with (gym_telemetry / names[2]).open(encoding="utf-8") as stream:
        gym_meta = json.load(stream)
    config_match = all(key in baseline_meta and key in gym_meta and
                       baseline_meta[key] == gym_meta[key] for key in CONFIG_FIELDS)
    baseline_snapshot = determinism(str(reference_telemetry), str(gym_telemetry), [100], [seed])
    nodes_match = window_rows(reference_telemetry / names[0], 0, NODE_INPUT_COLUMNS) == window_rows(
        gym_telemetry / names[0], 0, NODE_INPUT_COLUMNS)
    links_match = window_rows(reference_telemetry / names[1], 0, LINK_INPUT_COLUMNS) == window_rows(
        gym_telemetry / names[1], 0, LINK_INPUT_COLUMNS)
    return {"reference": str(reference_telemetry),
            "pass": bool(config_match and baseline_snapshot["pass"] and nodes_match and links_match),
            "configuration_match": config_match, "snapshot_and_dto_match": baseline_snapshot["pass"],
            "bigan_node_inputs_match": nodes_match, "bigan_link_inputs_match": links_match}


def adaptive_hybrid_route_gate(requests, metrics, isolated):
    result = {"live_telemetry_used": False, "isolation_matches_f2": False,
              "route_pairs_complete": False, "own_destinations_preserved": False,
              "blocked_next_hops_reported": False, "reroute_count_matches": False,
              "unresolved_count_matches": False}
    if [request.get("phase") for request in requests] != [0, 1]:
        return {**result, "pass": False, "reason": "expected Gym phases 0 and 1"}

    initial, live = requests
    isolated = sorted(set(int(node) for node in isolated))
    result["isolation_matches_f2"] = sorted(live.get("isolated", [])) == isolated
    live_state = live.get("live_state") or {}
    result["live_telemetry_used"] = (live.get("stage") == "live-telemetry-reroute" and
                                     live_state.get("measured_links", 0) > 0)
    initial_rows, live_rows = initial.get("routes", []), live.get("routes", [])
    initial_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                       for row in initial_rows}
    live_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                    for row in live_rows}
    result["route_pairs_complete"] = (len(initial_by_pair) == len(initial_rows) and
                                      len(live_by_pair) == len(live_rows) and
                                      set(initial_by_pair) == set(live_by_pair))
    if not result["route_pairs_complete"]:
        return {**result, "pass": False, "reason": "phase route pairs are incomplete or duplicated"}

    result["own_destinations_preserved"] = all(
        bool(initial_by_pair[pair]["own_dest"]) == bool(live_by_pair[pair]["own_dest"])
        for pair in initial_by_pair)
    all_changed = {pair for pair, before in initial_by_pair.items()
                   if (int(before["next_hop"]) != int(live_by_pair[pair]["next_hop"]) or
                       int(before["next_hop_is_sink"]) != int(live_by_pair[pair]["next_hop_is_sink"]))}
    # ApplyReroute (simulator) melewati sensor terisolasi: sensor itu membuang semua
    # transit, jadi host route-nya tidak diganti dan tidak masuk reroute_changed.
    changed = {pair for pair in all_changed if pair[0] not in isolated}
    failed_entries = {(int(row["node_id"]), int(row["dest_sink"]))
                      for row in live.get("failed_entries", [])}
    blocked_next_hops = {
        pair for pair, row in live_by_pair.items()
        if pair[0] not in isolated and not int(row["next_hop_is_sink"]) and
        int(row["next_hop"]) in isolated
    }
    result.update(changed_route_entries=len(changed),
                  changed_on_isolated_sensors=len(all_changed - changed),
                  measured_links=live_state.get("measured_links", 0),
                  failed_entries=len(failed_entries),
                  reroute_count_matches=metrics.get("reroute_changed") == len(changed),
                  blocked_next_hops_reported=blocked_next_hops.issubset(failed_entries),
                  unresolved_route_entries=len(blocked_next_hops),
                  unresolved_count_matches=metrics.get("reroute_unresolved") == len(blocked_next_hops))
    result["pass"] = all(result[key] for key in (
        "live_telemetry_used", "isolation_matches_f2", "route_pairs_complete",
        "own_destinations_preserved", "blocked_next_hops_reported",
        "reroute_count_matches", "unresolved_count_matches"))
    return result


def compare(audit, gym_dir, mode, control_dir=None):
    nodes, seed = audit["nodes"], audit["seed"]
    if nodes != 100 or seed not in (4, 5, 6):
        raise ValueError("stored baseline covers only 100 nodes and seeds 4-6")
    if audit["checkpoint_sha256"] != BASELINE_MODEL_SHA256 or audit["trust_source"] != "none":
        raise ValueError("audit does not match the frozen baseline policy")
    requests = audit["requests"]
    expected_phases = {"baseline": [0], "hybrid": [0, 1], "adaptive": [0, 1],
                       "adaptive_hybrid": [0, 1]}
    if mode not in expected_phases or [request["phase"] for request in requests] != expected_phases[mode]:
        raise ValueError("audit phases do not match selected mode")
    if mode == "adaptive_hybrid" and control_dir is None:
        raise ValueError("adaptive_hybrid mode requires its live-adaptive no-IDS Run A")

    initial = route_comparison(requests[0]["routes"], INPUTS / f"tldqn_nexthop_100_s{seed}.csv")
    result = {"nodes": nodes, "seed": seed, "mode": mode, "initial_routes": initial}
    if mode == "hybrid":
        with (DECISIONS / f"hybrid_decisions_100_s{seed}.csv").open(newline="") as stream:
            isolated = sorted(int(row["node_id"]) for row in csv.DictReader(stream)
                              if row["isolate"] == "1")
        if sorted(requests[1]["isolated"]) != isolated:
            raise ValueError("gym isolation input differs from baseline F2 decisions")
        result["reroute"] = route_comparison(
            requests[1]["routes"], DECISIONS / f"reroute_nexthop_100_s{seed}.csv")
    elif mode == "adaptive":
        if requests[1]["isolated"]:
            raise ValueError("TLDQN-only adaptive run must not include IDS isolation")
        if requests[1].get("stage") != "live-telemetry-reroute" or \
                requests[1].get("live_state") is None:
            raise ValueError("phase 1 is missing the live telemetry reroute")
        if control_dir is None:
            raise ValueError("adaptive mode requires a same-build CSV --control-dir")
    elif mode == "adaptive_hybrid":
        decision_dir = gym_dir / "decisions"
        if not decision_dir.is_dir():
            decision_dir = gym_dir.parent / "decisions"
        decision_path = decision_dir / f"hybrid_decisions_100_s{seed}.csv"
        meta_path = decision_dir / "hybrid_meta.json"
        if not decision_path.is_file() or not meta_path.is_file():
            raise ValueError("adaptive_hybrid mode requires copied F2 decisions and hybrid_meta.json")
        with meta_path.open(encoding="utf-8") as stream:
            hybrid_meta = json.load(stream)
        if hybrid_meta.get("fusion") != "F2":
            raise ValueError("adaptive_hybrid mode requires F2 decisions")
        with decision_path.open(newline="") as stream:
            decision_rows = list(csv.DictReader(stream))
        if len(decision_rows) != nodes:
            raise ValueError("F2 decision count does not match simulator nodes")
        expected_isolated = []
        for row in decision_rows:
            isolated = row["dto_decision"] == "malicious"
            if ((row["isolate"] == "1") != isolated or
                    row["reason"] != ("dto" if isolated else "none")):
                raise ValueError("decision rows do not follow the F2 isolation rule")
            if isolated:
                expected_isolated.append(int(row["node_id"]))
        gym_metrics = load_metrics(gym_dir / "metrics.csv")
        route_gate = adaptive_hybrid_route_gate(requests, gym_metrics, expected_isolated)
        if not route_gate["pass"]:
            raise ValueError(f"adaptive F2 route gate failed: {route_gate}")
        alarms = sum(row["bigan_pred"] == "1" for row in decision_rows)
        if (gym_metrics.get("ids_mode") != 1 or gym_metrics.get("hybrid_pilot_bigan") != 1 or
                gym_metrics.get("nodes_blocked") != len(expected_isolated) or
                gym_metrics.get("isolated_by_dto") != len(expected_isolated) or
                gym_metrics.get("isolated_by_bigan_only") != 0 or
                gym_metrics.get("bigan_alarms") != alarms):
            raise ValueError("simulator metrics do not match the applied F2 decisions")
        result["f2_gate"] = {**route_gate, "nodes_blocked": len(expected_isolated),
                             "bigan_alarms": alarms}

    baseline_dir = (control_dir if mode == "adaptive_hybrid" else
                    BASE_B if mode == "hybrid" else BASE_A)
    baseline_metrics = (baseline_dir / "metrics.csv" if mode == "adaptive_hybrid" else
                        baseline_dir / f"metrics_100_s{seed}.csv")
    result["metrics"] = metric_comparison(baseline_metrics, gym_dir / "metrics.csv")
    reference_dir = control_dir if mode == "adaptive_hybrid" else BASE_A
    result["causal_gate"] = causal_gate(gym_dir, seed, reference_dir)
    if control_dir is not None:
        control_metrics = control_dir / "metrics.csv"
        gym_metrics = gym_dir / "metrics.csv"
        control_causal = causal_gate(gym_dir, seed, control_dir)
        result["same_build_control"] = {
            "causal_gate": control_causal,
            "metrics": metric_comparison(control_metrics, gym_metrics),
            "metrics_identical_except_wallclock": compare_metrics(
                str(control_metrics), str(gym_metrics), metrics=True),
        }
        if mode == "adaptive":
            initial_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                               for row in requests[0]["routes"]}
            live_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                            for row in requests[1]["routes"]}
            same_pairs = set(initial_by_pair) == set(live_by_pair)
            same_destinations = same_pairs and all(
                initial_by_pair[pair]["own_dest"] == live_by_pair[pair]["own_dest"]
                for pair in initial_by_pair)
            changed = sorted(pair for pair in set(initial_by_pair) & set(live_by_pair)
                             if (int(initial_by_pair[pair]["next_hop"]) !=
                                 int(live_by_pair[pair]["next_hop"]) or
                                 int(initial_by_pair[pair]["next_hop_is_sink"]) !=
                                 int(live_by_pair[pair]["next_hop_is_sink"])))
            live_state = requests[1].get("live_state") or {}
            reroute_metric = result["same_build_control"]["metrics"]["reroute_changed"]["gym"]
            adaptive_metrics = result["same_build_control"]["metrics"]
            ids_actions_disabled = (adaptive_metrics["nodes_blocked"]["gym"] == 0 and
                                    adaptive_metrics["bigan_alarms"]["gym"] == 0)
            action_gate = {
                "live_telemetry_used": live_state.get("measured_links", 0) > 0,
                "measured_links": live_state.get("measured_links", 0),
                "proxy_fallback_links": live_state.get("proxy_fallback_links"),
                "route_pairs_complete": same_pairs,
                "own_destinations_preserved": same_destinations,
                "changed_route_entries": len(changed),
                "simulator_reroute_changed": reroute_metric,
                "applied_route_count_matches": reroute_metric == len(changed),
                "ids_actions_disabled": ids_actions_disabled,
            }
            action_gate["pass"] = bool(
                action_gate["live_telemetry_used"] and action_gate["route_pairs_complete"] and
                action_gate["own_destinations_preserved"] and
                action_gate["applied_route_count_matches"] and
                action_gate["ids_actions_disabled"])
            result["live_action_gate"] = action_gate
            result["live_route_changes"] = [list(pair) for pair in changed]
            result["pass"] = bool(initial["match"] and control_causal["pass"] and
                                  action_gate["pass"])
        elif mode == "adaptive_hybrid":
            result["pass"] = bool(initial["match"] and control_causal["pass"] and
                                  result["f2_gate"]["pass"])
        else:
            route_parity = initial["match"] and (mode != "hybrid" or result["reroute"]["match"])
            result["pass"] = bool(route_parity and control_causal["pass"] and
                                  result["same_build_control"][
                                      "metrics_identical_except_wallclock"]["identical"])
    else:
        result["pass"] = bool(initial["match"] and result["causal_gate"]["pass"] and
                              (mode != "hybrid" or result["reroute"]["match"]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--gym-dir", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path,
                        help="same-build CSV control run directory")
    parser.add_argument("--mode", choices=("baseline", "hybrid", "adaptive", "adaptive_hybrid"), required=True)
    args = parser.parse_args(argv)
    with args.audit.open(encoding="utf-8") as stream:
        audit = json.load(stream)
    result = compare(audit, args.gym_dir, args.mode, args.control_dir)
    print(json.dumps(result, indent=1, allow_nan=False))
    return int(not result["pass"])


if __name__ == "__main__":
    raise SystemExit(main())
