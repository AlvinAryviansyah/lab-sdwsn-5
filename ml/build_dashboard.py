#!/usr/bin/env python3
"""
build_dashboard.py  --  End-to-End Performance Dashboard HieMulti-Block
----------------------------------------------------------------------
Membaca HANYA hasil yang sudah ada di repository (CSV/JSON hasil run NS-3 dan laporan
Python) lalu menulis satu berkas mandiri dashboard/index.html (tanpa CDN, tanpa
dependensi browser). Tidak menjalankan simulasi atau model; tidak mengubah hasil.

Sumber data (semua relatif terhadap repo):
  ns3-sim/results/metrics_<n>_s<seed>{,_greedy}.csv        langkah-1 (TLDQN trust GT, greedy)
  ns3-sim/results/timeseries_<n>_s<seed>{,_greedy}.csv     confusion Bi-GAN per window
  ns3-sim/results/step2/metrics_*_{stage1,stage2,ctrl0}.csv langkah-2
  ns3-sim/results/step2/telemetry_{stage1,stage2,ctrl0}/    telemetry NS-3 + audit watchdog
  ns3-sim/results/step2/trust_stage1/                       trust telemetry (input tahap-2)
  ns3-sim/results/{routes_stage1,routes_stage2,routes_greedy,.}/tldqn_nexthop_*.csv
  ns3-sim/results/bigan_decisions_<n>_s<seed>.csv          ground truth skenario (EVALUASI)
    ns3-sim/tldqn_gym/runs/{csv_control_adaptive_ns348,tldqn_live_adaptive}_100_s<seed>/ latest adaptive TLDQN A/B
  ml/reports/*.json                                         evaluasi NSL-KDD & langkah-2

Pemisahan: ground truth disimpan terpisah (D.gt) dan hanya dipakai untuk evaluasi di
browser; hasil NSL-KDD (offline) terpisah dari hasil NS-3.

Pemakaian:
  .venv/bin/python ml/build_dashboard.py        # -> dashboard/index.html
  python3 -m http.server 8050 --bind 127.0.0.1 --directory dashboard
"""

import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

import export_routes as X
import telemetry_schema as S
from honeycomb_topology import NODE_SWEEP, HoneycombTopology, parse_positions
from routing_env import EnvConfig

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(ROOT, "ns3-sim", "results")
S2 = os.path.join(RES, "step2")
REP = os.path.join(HERE, "reports")
TLDQN_GYM_RUNS = os.path.join(ROOT, "ns3-sim", "tldqn_gym", "runs")
SEEDS = [1, 2, 3]

# Konfigurasi run yang ADA di repo. facets dipakai filter dashboard.
CONFIGS = {
    "step1_tldqn": dict(label="Langkah-1 · TLDQN · trust ground-truth (tersimulasi dari label)",
                        short="TLDQN + trust GT", stage="step1", policy="TLDQN", trust="gt",
                        routes=RES, mdir=RES, tag="", telem=None, nodes=NODE_SWEEP),
    "step1_greedy": dict(label="Langkah-1 · Greedy · tanpa trust", short="Greedy",
                         stage="step1", policy="Greedy", trust="none_used",
                         routes=os.path.join(RES, "routes_greedy"), mdir=RES, tag="_greedy",
                         telem=None, nodes=NODE_SWEEP),
    "stage1": dict(label="Stage 1 · TLDQN · trust 0.5 (tanpa informasi)", short="Stage 1 (trust 0.5)",
                   stage="stage1", policy="TLDQN", trust="uniform",
                   routes=os.path.join(RES, "routes_stage1"), mdir=S2, tag="_stage1",
                   telem="telemetry_stage1", nodes=NODE_SWEEP),
    "stage2": dict(label="Stage 2 · TLDQN · trust telemetry", short="Stage 2 (trust telemetry)",
                   stage="stage2", policy="TLDQN", trust="telemetry",
                   routes=os.path.join(RES, "routes_stage2"), mdir=S2, tag="_stage2",
                   telem="telemetry_stage2", nodes=NODE_SWEEP),
    "ctrl0": dict(label="Kontrol · TLDQN · trust 0.5 · grayholeDrop=0", short="Kontrol (tanpa grayhole)",
                  stage="control", policy="TLDQN", trust="uniform",
                  routes=os.path.join(RES, "routes_stage1"), mdir=S2, tag="_ctrl0",
                  telem="telemetry_ctrl0", nodes=[20, 60, 100]),
}
METRIC_KEYS = [
    "pdr_percent", "packet_drop_ratio_percent", "throughput_kbps", "latency_ms",
    "energy_consumption_J", "network_lifetime_s", "grayhole_drops", "grayhole_not_dropped",
    "grayhole_drop_prob", "max_range_m", "benign_hops_per_rx_est", "planned_hops_mean",
    "TP", "TN", "FP", "FN", "dto_TP", "dto_TN", "dto_FP", "dto_FN",
    "nodes_blocked", "attackers_blocked", "isolated_by_dto", "isolated_by_bigan_only",
    "bigan_alarms", "reroute_changed", "reroute_unresolved", "windows",
    "control_overhead_mps", "computation_overhead_percent",
    "flowmon_udp_tx_packets", "flowmon_udp_rx_packets", "telemetry_ip_forward_udp_delivered",
    "flowmon_udp_times_forwarded", "wd_watches", "wd_forwarded", "wd_forwarded_late",
    "wd_unobserved_rxfail", "wd_unobserved_clean",
    "benign_pdr_percent", "benign_tx_packets", "benign_rx_packets",
]


def metric_values(metrics):
    """Nilai METRIC_KEYS untuk payload; non-finite (mis. benign_pdr_percent 'nan' saat
    tx sensor jujur = 0) menjadi None -> tampil N/A, bukan crash json allow_nan=False."""
    out = {}
    for name in METRIC_KEYS:
        value = metrics.get(name)
        out[name] = None if isinstance(value, float) and not np.isfinite(value) else value
    return out


def rel(p):
    return os.path.relpath(p, ROOT)


def read_table(path):
    nh = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            nh[(int(r["node_id"]), int(r["dest_sink"]))] = (int(r["next_hop"]),
                                                            int(r["next_hop_is_sink"]))
    return nh


def paths_from(nh, topo):
    n, out = topo.n, []
    for s in range(n):
        t = int(topo.dest[s]) - n
        cur, p = s, [s]
        for _ in range(n + 2):
            j, is_sink = nh[(cur, t)]
            p.append(n + j if is_sink else j)
            if is_sink:
                break
            cur = j
        out.append(p)
    return out


def ground_truth(n, s):
    return labels_from(os.path.join(RES, f"bigan_decisions_{n}_s{s}.csv"), n)


def labels_from(path, n):
    if not os.path.exists(path):
        return None
    labels = [None] * n
    with open(path, newline="") as stream:
        for row in csv.DictReader(stream):
            node = int(row["node_id"])
            label = int(row["actual_mal"])
            if not 0 <= node < n or labels[node] is not None or label not in (0, 1):
                raise ValueError(f"invalid scenario labels in {path}")
            labels[node] = label
    if any(label is None for label in labels):
        raise ValueError(f"incomplete scenario labels in {path}")
    return labels


def timeseries(path):
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            out.append([float(r["t"]), int(r["TP"]), int(r["TN"]), int(r["FP"]), int(r["FN"])])
    return out


def decision_rows(path, n, pilot=False):
    if not os.path.exists(path):
        return None
    rows = [None] * n
    with open(path, newline="") as stream:
        for row in csv.DictReader(stream):
            node = int(row["node_id"])
            if not 0 <= node < n or rows[node] is not None:
                raise ValueError(f"invalid or duplicate sensor in {path}")
            prediction = int(row["pred_intrusion"])
            score = float(row["score" if pilot else "anomaly_score"])
            threshold = float(row["threshold"])
            if prediction not in (0, 1) or not np.isfinite(score) or not np.isfinite(threshold):
                raise ValueError(f"invalid sensor prediction in {path}")
            rows[node] = {
                "pred": prediction,
                "score": score,
                "threshold": threshold,
            }
    if any(row is None for row in rows):
        raise ValueError(f"incomplete sensor decisions in {path}")
    return rows


def node_telemetry(directory, n, seed):
    paths = S.paths(directory, n, seed)
    if not os.path.exists(paths["node"]):
        return None
    totals = S.node_totals(S.load_nodes(paths["node"]), n)
    names = ("self_ip_orig_pkts", "self_ip_rx_pkts", "self_ip_local_pkts",
             "self_ip_fwd_pkts", "self_energy_j", "self_ip_drop_ttl",
             "self_ip_drop_no_route", "self_ip_drop_bad_checksum", "self_ip_drop_iface_down",
             "self_ip_drop_route_error", "self_ip_drop_frag_timeout", "self_ip_drop_duplicate",
             "self_ip_drop_other")
    return {"node": {name: totals[name].tolist() for name in names},
            "source": rel(paths["node"])}


def add_pilot_runs(data):
    pilot_configs = (
        ("pilot_validation", "Bi-GAN telemetry · original replay", (1, 2, 3),
         "bigan_replay_B_20261107_212956", "bigan_pilot", "predictions_A"),
        ("pilot_test", "Bi-GAN telemetry · held-out test", (4, 5, 6),
         "bigan_test_replay_20261107_215011", "bigan_pilot_test_4_6", "predictions_test_4_6"),
    )
    for key, label, seeds, result_dir, input_dir, predictions in pilot_configs:
        data["configs"][key] = {"label": label, "short": label, "stage": "pilot",
                                "policy": "TLDQN", "trust": "uniform", "telemetry": True,
                                "source": rel(os.path.join(RES, result_dir)),
                                "duration": 10, "detection_source": "NS-3 telemetry Bi-GAN",
                                "dto_available": False,
                                "threshold_policy": ("Selected using labeled validation seeds 1-3"
                                                     if key == "pilot_test" else
                                                     "Original threshold from benign calibration")}
        data["runs"][key] = {}
        for seed in seeds:
            n = 100
            metrics_path = os.path.join(RES, result_dir, f"metrics_{n}_s{seed}.csv")
            route_path = os.path.join(RES, input_dir, "routes", f"tldqn_nexthop_{n}_s{seed}.csv")
            scenario_path = os.path.join(RES, input_dir, "scenarios", f"bigan_decisions_{n}_s{seed}.csv")
            prediction_path = os.path.join(REP, "bigan_ns3_pilot", "pilot_20261107_211217",
                                           predictions, f"bigan_pilot_predictions_{n}_s{seed}.csv")
            if not os.path.exists(metrics_path):
                continue
            labels = labels_from(scenario_path, n)
            metrics = S.load_metrics(metrics_path)
            decisions = decision_rows(prediction_path, n, pilot=True)
            if labels is not None and decisions is not None and metrics.get("ids_mode") == 3:
                confusion = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
                for actual, decision in zip(labels, decisions):
                    key_name = ("TP" if actual else "FP") if decision["pred"] else ("FN" if actual else "TN")
                    confusion[key_name] += 1
                if any(metrics.get(name) != count for name, count in confusion.items()):
                    raise ValueError(f"pilot predictions do not match {metrics_path}")
            initial = [metrics.get(name) for name in ("TP", "TN", "FP", "FN")]
            timeline = ([[8.3] + initial] if metrics.get("ids_mode") == 3 and
                        metrics.get("windows") == 1 and all(value is not None for value in initial)
                        else None)
            data["runs"][key][f"{n}_{seed}"] = {
                "m": {name: metrics.get(name) for name in METRIC_KEYS},
                "paths": paths_from(read_table(route_path), HoneycombTopology(n))
                         if os.path.exists(route_path) else None,
                "ts": timeline, "ts_source": "NS-3 single decision at scheduled t=8.3 s",
                "gt": labels,
                "tel": node_telemetry(os.path.join(RES, result_dir), n, seed),
                "det": decisions,
                "metrics_source": rel(metrics_path),
            }
    data["seeds"] = sorted({int(key.split("_")[1]) for runs in data["runs"].values() for key in runs})


def hybrid_paths(decisions_path, route_path, base_path, n, topo):
    with open(decisions_path, newline="") as stream:
        decisions = list(csv.DictReader(stream))
    if len(decisions) != n:
        raise ValueError(f"incomplete hybrid decisions in {decisions_path}")
    dto = [None] * n
    blocked = set()
    for row in decisions:
        node = int(row["node_id"])
        if not 0 <= node < n or dto[node] is not None:
            raise ValueError(f"invalid hybrid decisions in {decisions_path}")
        dto[node] = row["dto_decision"]
        if row["isolate"] == "1":
            blocked.add(node)
    base = read_table(base_path)
    for pair, hop in read_table(route_path).items():
        if pair[0] not in blocked and (hop[1] or hop[0] not in blocked):
            base[pair] = hop
    paths = []
    for sensor in range(n):
        destination = int(topo.dest[sensor]) - n
        path, current = [sensor], sensor
        for _ in range(n + 1):
            if current in blocked or (current, destination) not in base:
                break
            next_hop, is_sink = base[(current, destination)]
            next_node = n + next_hop if is_sink else next_hop
            path.append(next_node)
            if is_sink or next_node in path[:-1]:
                break
            current = next_node
        paths.append(path)
    return decisions, dto, blocked, paths


def add_hybrid_runs(data):
    root = os.path.join(RES, "step4", "full")
    for variant in ("F2", "F1"):
        key = "hybrid_" + variant.lower()
        decision_dir = os.path.join(root, "dec_stage2_" + variant)
        telemetry_dir = os.path.join(root, "telemetry_s4fB_" + variant)
        data["configs"][key] = {"label": "Hybrid " + variant + " · legacy NSL-KDD",
                                "short": "Hybrid " + variant, "stage": "hybrid",
                                "policy": "TLDQN", "trust": "telemetry", "telemetry": True,
                                "source": rel(root), "duration": 600,
                                "detection_source": "NSL-KDD assigned by scenario label",
                                "dto_available": True}
        data["runs"][key] = {}
        for n in NODE_SWEEP:
            topo = HoneycombTopology(n)
            for seed in SEEDS:
                tag = f"{n}_s{seed}"
                metrics_path = os.path.join(root, f"metrics_{tag}_s4fB_{variant}.csv")
                decisions_path = os.path.join(decision_dir, f"hybrid_decisions_{tag}.csv")
                route_path = os.path.join(decision_dir, f"reroute_nexthop_{tag}.csv")
                if not all(os.path.exists(path) for path in (metrics_path, decisions_path, route_path)):
                    continue
                base_path = os.path.join(RES, "routes_stage2", f"tldqn_nexthop_{tag}.csv")
                _, dto, blocked, paths = hybrid_paths(decisions_path, route_path, base_path, n, topo)
                metrics = S.load_metrics(metrics_path)
                timeseries_path = os.path.join(root, f"timeseries_{tag}_s4fB_{variant}.csv")
                data["runs"][key][f"{n}_{seed}"] = {
                    "m": {name: metrics.get(name) for name in METRIC_KEYS}, "paths": paths,
                    "ts": timeseries(timeseries_path) if os.path.exists(timeseries_path) else None,
                    "gt": data["gt"][f"{n}_{seed}"], "dto": dto, "blocked": sorted(blocked),
                    "tel": node_telemetry(telemetry_dir, n, seed),
                    "det": decision_rows(os.path.join(RES, f"bigan_decisions_{tag}.csv"), n),
                    "metrics_source": rel(metrics_path),
                }


def validate_telemetry_hybrid(decisions, predictions, metrics, labels):
    n = len(predictions)
    if len(decisions) != n or len(labels) != n:
        raise ValueError("hybrid telemetry sensor count mismatch")
    if metrics.get("ids_mode") != 1 or metrics.get("hybrid_pilot_bigan") != 1:
        raise ValueError("metrics are not from hybrid telemetry replay")
    seen = set()
    counts = {name: 0 for name in ("TP", "TN", "FP", "FN")}
    dto_counts = {name: 0 for name in ("TP", "TN", "FP", "FN")}
    alarms = isolated = 0
    for row in decisions:
        node = int(row["node_id"])
        if not 0 <= node < n or node in seen:
            raise ValueError("invalid or duplicate hybrid sensor")
        seen.add(node)
        dto = row["dto_decision"]
        if dto not in ("malicious", "normal", "insufficient_evidence"):
            raise ValueError("invalid DTO decision")
        pred, isolate = int(row["bigan_pred"]), int(row["isolate"])
        if pred != predictions[node]["pred"] or isolate != int(dto == "malicious"):
            raise ValueError("hybrid decision does not match pilot prediction or F2")
        actual = bool(labels[node])
        for result, positive in ((counts, bool(pred)), (dto_counts, dto == "malicious")):
            key = ("TP" if actual else "FP") if positive else ("FN" if actual else "TN")
            result[key] += 1
        alarms += pred
        isolated += isolate
    if metrics.get("bigan_alarms") != alarms or metrics.get("nodes_blocked") != isolated:
        raise ValueError("hybrid replay alarm or isolation count mismatch")
    if any(metrics.get(key) != value or metrics.get("dto_" + key) != dto_counts[key]
           for key, value in counts.items()):
        raise ValueError("hybrid replay confusion matrix mismatch")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_hybrid_sources(meta, paths):
    for key, path in paths.items():
        if meta.get(key) != file_sha256(path):
            raise ValueError(f"hybrid provenance mismatch: {path}")


def hybrid_replay_gate(source_dir, replay_dir, n, seed):
    source = S.paths(source_dir, n, seed)
    replay = S.paths(replay_dir, n, seed)
    tag = f"{n}_s{seed}"
    required = [source["node"], source["links"], replay["node"], replay["links"],
                os.path.join(source_dir, f"ids_snapshot_{tag}.csv"),
                os.path.join(replay_dir, f"ids_snapshot_{tag}.csv")]
    if not all(os.path.exists(path) for path in required):
        return None
    from bigan_ns3_pilot import _matrix, extract_window
    from hybrid_eval import determinism
    original, _ = extract_window(source_dir, n, seed, 0)
    replayed, _ = extract_window(replay_dir, n, seed, 0)
    ids_match = [row["node_id"] for row in original] == [row["node_id"] for row in replayed]
    return bool(ids_match and np.array_equal(_matrix(original), _matrix(replayed)) and
                determinism(source_dir, replay_dir, [n], [seed])["pass"])


def add_telemetry_hybrid_runs(data):
    key = "hybrid_telemetry_f2"
    results = os.path.join(RES, "bigan_hybrid_f2_4_6")
    decisions_dir = os.path.join(RES, "bigan_hybrid_f2_decisions_4_6")
    source_dir = os.path.join(RES, "bigan_test_4_6_20261107_214507")
    inputs = os.path.join(RES, "bigan_pilot_test_4_6")
    predictions_dir = os.path.join(REP, "bigan_ns3_pilot", "pilot_20261107_211217",
                                   "predictions_test_4_6")
    data["configs"][key] = {"label": "Integrasi NS-3 · TLDQN + DTO + Bi-GAN",
                            "short": "Hybrid F2 telemetry", "stage": "hybrid",
                            "policy": "TLDQN", "trust": "uniform", "telemetry": True,
                            "source": rel(results), "duration": 10,
                            "detection_source": "NS-3 telemetry Bi-GAN",
                            "threshold_policy": "Selected using labeled validation seeds 1-3",
                            "dto_available": True}
    data["runs"][key] = {}
    meta_path = os.path.join(decisions_dir, "hybrid_meta.json")
    if not os.path.exists(meta_path):
        return
    with open(meta_path) as stream:
        hybrid_meta = json.load(stream)
    if hybrid_meta.get("fusion") != "F2":
        raise ValueError("hybrid telemetry dashboard requires F2 decisions")
    for seed in (4, 5, 6):
        n = 100
        tag = f"{n}_s{seed}"
        metrics_path = os.path.join(results, f"metrics_{tag}.csv")
        decisions_path = os.path.join(decisions_dir, f"hybrid_decisions_{tag}.csv")
        route_path = os.path.join(decisions_dir, f"reroute_nexthop_{tag}.csv")
        base_path = os.path.join(inputs, "routes", f"tldqn_nexthop_{tag}.csv")
        scenario_path = os.path.join(inputs, "scenarios", f"bigan_decisions_{tag}.csv")
        prediction_path = os.path.join(predictions_dir, f"bigan_pilot_predictions_{tag}.csv")
        if not all(os.path.exists(path) for path in
                   (metrics_path, decisions_path, route_path, base_path, scenario_path, prediction_path)):
            continue
        labels = labels_from(scenario_path, n)
        predictions = decision_rows(prediction_path, n, pilot=True)
        if f"{tag}" not in hybrid_meta.get("scenarios", {}):
            raise ValueError(f"missing hybrid provenance for {tag}")
        provenance = hybrid_meta["scenarios"][tag]
        source_paths = S.paths(source_dir, n, seed)
        validate_hybrid_sources(provenance, {
            "telemetry_node_sha256": source_paths["node"],
            "telemetry_links_sha256": source_paths["links"],
            "telemetry_meta_sha256": source_paths["meta"],
            "bigan_sha256": prediction_path, "route_table_sha256": base_path,
            "decisions_sha256": decisions_path, "reroute_sha256": route_path,
        })
        decisions, dto, blocked, route_paths = hybrid_paths(
            decisions_path, route_path, base_path, n, HoneycombTopology(n))
        metrics = S.load_metrics(metrics_path)
        validate_telemetry_hybrid(decisions, predictions, metrics, labels)
        if metrics.get("reroute_changed") != len(provenance["reroute"]["changed_entries"]):
            raise ValueError(f"hybrid replay reroute count mismatch for {tag}")
        initial = [metrics.get(name) for name in ("TP", "TN", "FP", "FN")]
        timeline = [[8.3] + initial] if metrics.get("windows") == 1 else None
        data["runs"][key][f"{n}_{seed}"] = {
            "m": {name: metrics.get(name) for name in METRIC_KEYS}, "paths": route_paths,
            "ts": timeline, "ts_source": "NS-3 single decision at scheduled t=8.3 s",
            "gt": labels, "dto": dto, "blocked": sorted(blocked),
            "tel": node_telemetry(results, n, seed), "det": predictions,
            "metrics_source": rel(metrics_path),
            "replay_verified": hybrid_replay_gate(source_dir, results, n, seed),
        }


def add_baseline_runs(data):
    key = "baseline_no_ids"
    source_dir = os.path.join(RES, "bigan_test_4_6_20261107_214507")
    inputs = os.path.join(RES, "bigan_pilot_test_4_6")
    data["configs"][key] = {"label": "Baseline · NS-3 tanpa IDS",
                            "short": "Baseline tanpa IDS", "stage": "baseline",
                            "policy": "TLDQN", "trust": "uniform", "telemetry": True,
                            "source": rel(source_dir), "duration": 10,
                            "detection_source": "No IDS action", "dto_available": False}
    data["runs"][key] = {}
    for seed in (4, 5, 6):
        n = 100
        tag = f"{n}_s{seed}"
        metrics_path = os.path.join(source_dir, f"metrics_{tag}.csv")
        route_path = os.path.join(inputs, "routes", f"tldqn_nexthop_{tag}.csv")
        scenario_path = os.path.join(inputs, "scenarios", f"bigan_decisions_{tag}.csv")
        if not all(os.path.exists(path) for path in (metrics_path, route_path, scenario_path)):
            continue
        metrics = S.load_metrics(metrics_path)
        if metrics.get("ids_mode") != 2:
            raise ValueError(f"baseline is not an IDS-disabled run: {metrics_path}")
        values = {name: metrics.get(name) for name in METRIC_KEYS}
        for name in ("TP", "TN", "FP", "FN", "dto_TP", "dto_TN", "dto_FP", "dto_FN", "windows"):
            values[name] = None
        data["runs"][key][f"{n}_{seed}"] = {
            "m": values, "paths": paths_from(read_table(route_path), HoneycombTopology(n)),
            "ts": None, "gt": labels_from(scenario_path, n), "det": None,
            "tel": node_telemetry(source_dir, n, seed), "metrics_source": rel(metrics_path),
        }


def paths_from_gym_rows(rows, n, topo, blocked):
    routes = {}
    for row in rows:
        pair = (int(row["node_id"]), int(row["dest_sink"]))
        if pair in routes:
            raise ValueError(f"duplicate Gym route entry: {pair}")
        routes[pair] = (int(row["next_hop"]), int(row["next_hop_is_sink"]))

    paths = []
    for sensor in range(n):
        destination = int(topo.dest[sensor]) - n
        path, current = [sensor], sensor
        for _ in range(n + 1):
            if current in blocked or (current, destination) not in routes:
                break
            next_hop, is_sink = routes[(current, destination)]
            next_node = n + next_hop if is_sink else next_hop
            path.append(next_node)
            if is_sink or next_node in path[:-1]:
                break
            current = next_node
        paths.append(path)
    return paths


def add_latest_tldqn_ns3gym_runs(data, runs_root=None):
    runs_root = runs_root or TLDQN_GYM_RUNS
    csv_key, gym_key, hybrid_key = ("tldqn_csv_control", "tldqn_ns3gym_adaptive",
                                    "tldqn_ns3gym_adaptive_f2")
    data["active_configs"] = [csv_key, gym_key, hybrid_key]
    common = {"stage": "baseline", "telemetry": True, "duration": 10,
              "detection_source": "No IDS action", "dto_available": False}
    data["configs"][csv_key] = {
        **common, "label": "1 · Baseline · TLDQN dari CSV",
        "short": "Baseline CSV", "policy": "TLDQN (CSV control)", "trust": "uniform",
        "route_transport": "csv",
        "source": rel(runs_root),
    }
    data["configs"][gym_key] = {
        **common, "label": "2 · Adaptive live Gym · TLDQN via ns3-gym",
        "short": "Adaptive Gym", "policy": "TLDQN + ns3-gym", "trust": "live",
        "route_transport": "ns3-gym-live",
        "source": rel(runs_root),
    }
    data["configs"][hybrid_key] = {
        **common, "label": "3 · Adaptive live Gym + isolasi sensor malicious (F2)",
        "short": "Gym + isolasi", "stage": "hybrid", "dto_available": True,
        "policy": "TLDQN + ns3-gym", "trust": "live", "route_transport": "ns3-gym-live",
        "detection_source": "NS-3 telemetry Bi-GAN", "fusion": "F2",
        "threshold_policy": "Frozen threshold selected on labeled validation seeds 1-3",
        "source": rel(runs_root),
    }
    data["runs"][csv_key] = {}
    data["runs"][gym_key] = {}
    data["runs"][hybrid_key] = {}

    input_dir = os.path.join(RES, "bigan_pilot_test_4_6")
    for seed in (4, 5, 6):
        n = 100
        tag = f"{n}_s{seed}"
        run_key = f"{n}_{seed}"
        control_dir = os.path.join(runs_root, f"csv_control_adaptive_ns348_{tag}")
        gym_root = os.path.join(runs_root, f"tldqn_live_adaptive_{tag}")
        gym_dir = gym_simulation_dir(gym_root)
        control_dir = gym_simulation_dir(control_dir)
        control_metrics = os.path.join(control_dir, "metrics.csv")
        gym_metrics = os.path.join(gym_dir, "metrics.csv")
        audit_path = os.path.join(gym_root, "audit.json")
        base_route_path = os.path.join(input_dir, "routes", f"tldqn_nexthop_{tag}.csv")
        scenario_path = os.path.join(input_dir, "scenarios", f"bigan_decisions_{tag}.csv")
        required = (control_metrics, gym_metrics, audit_path, base_route_path, scenario_path)
        if not run_complete("Baseline CSV + Adaptive Gym", seed, required):
            continue

        gym_tool_dir = os.path.join(ROOT, "ns3-sim", "tldqn_gym")
        if gym_tool_dir not in sys.path:
            sys.path.insert(0, gym_tool_dir)
        from check_parity import compare as compare_gym_run

        with open(audit_path, encoding="utf-8") as stream:
            audit = json.load(stream)
        parity = compare_gym_run(audit, Path(gym_dir), "adaptive", Path(control_dir))
        labels = labels_from(scenario_path, n)
        topology = HoneycombTopology(n)
        control_paths = paths_from(read_table(base_route_path), topology)
        gym_paths = paths_from_gym_rows(audit["requests"][1]["routes"], n, topology, set())
        control_m = S.load_metrics(control_metrics)
        gym_m = S.load_metrics(gym_metrics)
        live_state = audit["requests"][1].get("live_state") or {}
        initial_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                           for row in audit["requests"][0]["routes"]}
        live_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                        for row in audit["requests"][1]["routes"]}
        route_changes = []
        for pair in sorted(set(initial_by_pair) & set(live_by_pair)):
            old, new = initial_by_pair[pair], live_by_pair[pair]
            if (int(old["next_hop"]) != int(new["next_hop"]) or
                    int(old["next_hop_is_sink"]) != int(new["next_hop_is_sink"])):
                old_type = "sink" if int(old["next_hop_is_sink"]) else "sensor"
                new_type = "sink" if int(new["next_hop_is_sink"]) else "sensor"
                route_changes.append({"node": pair[0], "sink": pair[1],
                                      "before": f"{old_type}:{old['next_hop']}",
                                      "after": f"{new_type}:{new['next_hop']}"})

        def make_run(metrics, paths, metrics_path, telemetry_dir, transport):
            values = metric_values(metrics)
            for name in ("TP", "TN", "FP", "FN", "dto_TP", "dto_TN", "dto_FP", "dto_FN",
                         "windows"):
                values[name] = None
            return {
                "m": values, "paths": paths, "ts": None, "gt": labels,
                "dto": None, "blocked": [], "tel": node_telemetry(telemetry_dir, n, seed),
                "det": None, "metrics_source": rel(metrics_path),
                "replay_verified": parity["pass"], "same_build_parity": parity,
                "live_state": live_state if transport == "ns3-gym-live" else None,
                "live_route_changes": route_changes if transport == "ns3-gym-live" else [],
                "live_inference_ms": audit["requests"][1].get("inference_wall_ms")
                    if transport == "ns3-gym-live" else None,
            }

        data["runs"][csv_key][run_key] = make_run(
            control_m, control_paths, control_metrics, os.path.join(control_dir, "telemetry"), "csv")
        data["runs"][gym_key][run_key] = make_run(
            gym_m, gym_paths, gym_metrics, os.path.join(gym_dir, "telemetry"), "ns3-gym-live")


def run_complete(mode, seed, required):
    """True bila semua artefak ada. Seed yang tidak lengkap DILEWATI (tampil "Pending"
    di dashboard), tetapi dilaporkan ke stderr agar tidak hilang diam-diam."""
    missing = [path for path in required if not os.path.isfile(path)]
    if not missing:
        return True
    if len(missing) < len(required):          # sebagian ada -> run setengah jadi
        print(f"[peringatan] {mode} seed {seed} TIDAK LENGKAP, dilewati; file hilang:",
              file=sys.stderr)
        for path in missing:
            print(f"    - {rel(path)}", file=sys.stderr)
    else:
        print(f"[info] {mode} seed {seed} belum dijalankan.", file=sys.stderr)
    return False


def gym_simulation_dir(run_root):
    nested = os.path.join(run_root, "ns3")
    return nested if os.path.isdir(nested) else run_root


def add_adaptive_f2_runs(data, runs_root=None):
    runs_root = runs_root or TLDQN_GYM_RUNS
    key = "tldqn_ns3gym_adaptive_f2"
    input_dir = os.path.join(RES, "bigan_pilot_test_4_6")
    gym_tool_dir = os.path.join(ROOT, "ns3-sim", "tldqn_gym")
    if gym_tool_dir not in sys.path:
        sys.path.insert(0, gym_tool_dir)
    from check_parity import compare as compare_gym_run

    for seed in (4, 5, 6):
        n = 100
        tag = f"{n}_s{seed}"
        run_key = f"{n}_{seed}"   # sama dgn mode lain & template (`100_${seed}`)
        control_root = os.path.join(runs_root, f"tldqn_live_adaptive_{tag}")
        control_dir = gym_simulation_dir(control_root)
        hybrid_root = os.path.join(runs_root, f"tldqn_live_hybrid_f2_{tag}")
        gym_dir = gym_simulation_dir(hybrid_root)
        decisions_dir = os.path.join(hybrid_root, "decisions")
        prediction_path = os.path.join(hybrid_root, "predictions",
                                       f"bigan_pilot_predictions_{tag}.csv")
        audit_path = os.path.join(hybrid_root, "audit.json")
        decisions_path = os.path.join(decisions_dir, f"hybrid_decisions_{tag}.csv")
        meta_path = os.path.join(decisions_dir, "hybrid_meta.json")
        metrics_path = os.path.join(gym_dir, "metrics.csv")
        base_route_path = os.path.join(input_dir, "routes", f"tldqn_nexthop_{tag}.csv")
        scenario_path = os.path.join(input_dir, "scenarios", f"bigan_decisions_{tag}.csv")
        required = (audit_path, decisions_path, meta_path, prediction_path, metrics_path,
                    os.path.join(control_dir, "metrics.csv"), base_route_path, scenario_path)
        if not run_complete("Adaptive Gym + isolasi (F2)", seed, required):
            continue

        with open(audit_path, encoding="utf-8") as stream:
            audit = json.load(stream)
        parity = compare_gym_run(audit, Path(gym_dir), "adaptive_hybrid", Path(control_dir))
        labels = labels_from(scenario_path, n)
        predictions = decision_rows(prediction_path, n, pilot=True)
        with open(decisions_path, newline="") as stream:
            decisions = list(csv.DictReader(stream))
        metrics = S.load_metrics(metrics_path)
        validate_telemetry_hybrid(decisions, predictions, metrics, labels)
        hybrid_topology = HoneycombTopology(n)
        blocked = sorted(int(row["node_id"]) for row in decisions if row["isolate"] == "1")
        initial_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                           for row in audit["requests"][0]["routes"]}
        live_routes = audit["requests"][1]["routes"]
        live_by_pair = {(int(row["node_id"]), int(row["dest_sink"])): row
                        for row in live_routes}
        route_changes = []
        for pair in sorted(set(initial_by_pair) & set(live_by_pair)):
            before, after = initial_by_pair[pair], live_by_pair[pair]
            if (int(before["next_hop"]) != int(after["next_hop"]) or
                    int(before["next_hop_is_sink"]) != int(after["next_hop_is_sink"])):
                old_type = "sink" if int(before["next_hop_is_sink"]) else "sensor"
                new_type = "sink" if int(after["next_hop_is_sink"]) else "sensor"
                route_changes.append({"node": pair[0], "sink": pair[1],
                                      "before": f"{old_type}:{before['next_hop']}",
                                      "after": f"{new_type}:{after['next_hop']}"})
        route_paths = paths_from_gym_rows(live_routes, n, hybrid_topology, set(blocked))
        with open(meta_path, encoding="utf-8") as stream:
            decision_meta = json.load(stream)
        provenance = decision_meta.get("scenarios", {}).get(tag, {})
        # Run Gym menulis telemetry di <run>/ns3/telemetry (bukan langsung di ns3/).
        source_telemetry = S.paths(os.path.join(control_dir, "telemetry"), n, seed)
        route_path = os.path.join(decisions_dir, f"reroute_nexthop_{tag}.csv")
        validate_hybrid_sources(provenance, {
            "telemetry_node_sha256": source_telemetry["node"],
            "telemetry_links_sha256": source_telemetry["links"],
            "telemetry_meta_sha256": source_telemetry["meta"],
            "bigan_sha256": prediction_path,
            "bigan_metadata_sha256": prediction_path + ".meta.json",
            "route_table_sha256": base_route_path,
            "decisions_sha256": decisions_path,
            "reroute_sha256": route_path,
        })
        data["runs"][key][run_key] = {
            "m": metric_values(metrics),
            "paths": route_paths, "ts": None, "gt": labels,
            "dto": [row["dto_decision"] for row in decisions], "blocked": blocked,
            "tel": node_telemetry(os.path.join(gym_dir, "telemetry"), n, seed),
            "det": predictions, "metrics_source": rel(metrics_path),
            "replay_verified": parity["pass"], "same_build_parity": parity,
            "f2_meta": provenance, "f2_gate": parity.get("f2_gate"),
            "live_state": audit["requests"][1].get("live_state"),
            "live_route_changes": route_changes,
        }


def trust_file(n, s):
    p = os.path.join(S2, "trust_stage1", f"trust_telemetry_{n}_s{s}.csv")
    if not os.path.exists(p):
        return None
    rows = {}
    with open(p) as f:
        for r in csv.DictReader(f):
            rows[int(r["node_id"])] = [round(float(r[k]), 6) for k in
                                       ("trust", "n_watched", "n_forwarded", "n_ambiguous",
                                        "n_unobserved_clean", "drops_est")]
    return [rows[i] for i in range(n)]


def telemetry_view(tdir, n, s, paths):
    """Ringkasan telemetry per node dan per hop rute untuk satu run."""
    p = S.paths(os.path.join(S2, tdir), n, s)
    if not os.path.exists(p["node"]):
        return None
    tot = S.node_totals(S.load_nodes(p["node"]), n)
    node = {k: [round(float(v), 6) for v in tot[k]] for k in
            ("obs_watched", "obs_forwarded", "obs_forwarded_late", "obs_unobserved_rxfail",
             "obs_unobserved_clean", "self_ip_fwd_pkts", "self_ip_orig_pkts", "self_energy_j",
             "self_ip_rx_pkts", "self_ip_local_pkts", "self_ip_drop_ttl",
             "self_ip_drop_no_route", "self_ip_drop_bad_checksum", "self_ip_drop_iface_down",
             "self_ip_drop_route_error", "self_ip_drop_frag_timeout", "self_ip_drop_duplicate",
             "self_ip_drop_other", "self_phy_rx_fail_mpdu", "self_phy_rx_drop")}
    # audit (kebenaran simulator) per node yang diamati: [dipancarkan, total watch]
    aud = None
    if os.path.exists(p["audit"]):
        aud = np.zeros((n, 2))
        for r in S.load_audit(p["audit"]):
            aud[r["neighbor"], 1] += r["count"]
            if r["true_cause"].startswith("j_tx_"):
                aud[r["neighbor"], 0] += r["count"]
    # kualitas tautan per hop rute (agregat semua window)
    want = {(a, b) for pth in paths for a, b in zip(pth[:-1], pth[1:])}
    agg = {}
    for r in S.load_links(p["links"]) if os.path.exists(p["links"]) else []:
        j = r["neighbor_id"] if r["neighbor_type"] == "sensor" else (
            n + r["neighbor_id"] if r["neighbor_type"] == "sink" else None)
        if j is None or (r["observer"], j) not in want:
            continue
        a = agg.setdefault((r["observer"], j), [0.0, 0.0, 0, 0, 0, 0])
        if r["rx_ok_from"]:
            a[0] += r["rssi_mean_dbm"] * r["rx_ok_from"]
            a[1] += r["snr_mean_db"] * r["rx_ok_from"]
            a[2] += r["rx_ok_from"]
        a[3] += r["mac_handoff_acked"]
        a[4] += r["mac_ack_timeout"]
        a[5] += r["mac_handoff_drop_retry"]
    hops = {f"{c}-{j}": [round(v[0] / v[2], 2) if v[2] else None,
                         round(v[1] / v[2], 2) if v[2] else None, v[3], v[4], v[5]]
            for (c, j), v in agg.items()}
    return {"node": node, "audit": aud.astype(int).tolist() if aud is not None else None, "hops": hops,
            "source": rel(p["node"])}


def audit_matrix(tdir, nodes):
    out = {}
    for n in nodes:
        for s in SEEDS:
            p = S.paths(os.path.join(S2, tdir), n, s)["audit"]
            if not os.path.exists(p):
                continue
            m = {}
            for r in S.load_audit(p):
                m[f"{r['wd_category']}|{r['true_cause']}"] = m.get(
                    f"{r['wd_category']}|{r['true_cause']}", 0) + r["count"]
            out[f"{n}_{s}"] = m
    return out


def link_model(n, s, mal, paths_all):
    """Link quality MODEL Python (prr x stability) = masukan TLDQN, per hop yang dipakai."""
    env = X.build_env(n, s, np.zeros(n, bool), EnvConfig(), "none")  # tidak memakai label
    lq = {}
    for paths in paths_all:
        for p in paths:
            for a, b in zip(p[:-1], p[1:]):
                lq[f"{a}-{b}"] = round(float(env.prr[a, b] * env.stability[a, b]), 4)
    return lq


def load_json(name):
    p = os.path.join(REP, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as stream:
        return json.load(stream)


def load_ai_timing():
    path = os.path.join(RES, "ai_timing.csv")
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as stream:
        return {row["n"]: {"bigan": float(row["bigan_ms_per_decision"]),
                           "tldqn": float(row["tldqn_ms_per_decision"])}
                for row in csv.DictReader(stream)}


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:
        return "unknown"


def build(latest_only=False):
    sens, sinks = parse_positions()
    D = {"meta": {"built_at": time.strftime("%Y-%m-%d %H:%M"), "git": git_rev(),
                 "ns3": "ns-3.48, 802.11ac 80 MHz, jangkauan 150 m; latest adaptive TLDQN run: 100 nodes",
                  "grayhole": "relay malicious menjatuhkan 70% paket transit"},
         "nodes": NODE_SWEEP, "seeds": SEEDS,
         "sensors": sens.round(2).tolist(), "sinks": sinks.round(2).tolist(),
         "configs": {}, "runs": {}, "gt": {}, "trust": {}, "lq": {}, "audit": {},
         "ai_timing": load_ai_timing()}
    if latest_only:
        add_latest_tldqn_ns3gym_runs(D)
        add_adaptive_f2_runs(D)
        return D
    for k, c in CONFIGS.items():
        D["configs"][k] = {f: c[f] for f in ("label", "short", "stage", "policy", "trust")}
        D["configs"][k]["telemetry"] = c["telem"] is not None
        D["configs"][k]["source"] = rel(os.path.join(c["mdir"], f"metrics_<n>_s<seed>{c['tag']}.csv"))
        D["runs"][k] = {}
    for n in NODE_SWEEP:
        topo = HoneycombTopology(n)
        for s in SEEDS:
            key = f"{n}_{s}"
            D["gt"][key] = ground_truth(n, s)
            D["trust"][key] = trust_file(n, s)
            # Trust yang DIPAKAI run langkah-1 TLDQN: reputasi tersimulasi dari label,
            # direproduksi deterministik persis seperti export_routes (RNG 20000*seed+n).
            if D["gt"][key] is not None:
                env_sim = X.build_env(n, s, np.array(D["gt"][key], bool), EnvConfig(), "simulated")
                D.setdefault("trust_sim", {})[key] = [round(float(v), 4) for v in env_sim.trust[:n]]
            paths_all = []
            for k, c in CONFIGS.items():
                if n not in c["nodes"]:
                    continue
                mp = os.path.join(c["mdir"], f"metrics_{n}_s{s}{c['tag']}.csv")
                if not os.path.exists(mp):
                    continue
                m = S.load_metrics(mp)
                route_path = os.path.join(c["routes"], f"tldqn_nexthop_{n}_s{s}.csv")
                paths = paths_from(read_table(route_path), topo) if os.path.exists(route_path) else None
                if paths is not None:
                    paths_all.append(paths)
                tsp = os.path.join(c["mdir"], f"timeseries_{n}_s{s}{c['tag']}.csv")
                run = {"m": {mk: m.get(mk) for mk in METRIC_KEYS}, "paths": paths,
                      "ts": timeseries(tsp) if os.path.exists(tsp) else None,
                      "gt": D["gt"][key],
                      "det": decision_rows(os.path.join(RES, f"bigan_decisions_{n}_s{s}.csv"), n),
                      "metrics_source": rel(mp)}
                if c["telem"]:
                    run["tel"] = telemetry_view(c["telem"], n, s, paths or [])
                D["runs"][k][key] = run
            D["lq"][key] = link_model(n, s, D["gt"][key], paths_all)
    add_pilot_runs(D)
    add_hybrid_runs(D)
    add_telemetry_hybrid_runs(D)
    add_baseline_runs(D)
    add_latest_tldqn_ns3gym_runs(D)
    add_adaptive_f2_runs(D)
    for k, c in CONFIGS.items():
        if c["telem"]:
            D["audit"][k] = audit_matrix(c["telem"], c["nodes"])
    bg = load_json("bigan_eval_bigan_v2_h2.json")
    D["nslkdd"] = None if bg is None else {
        "checkpoint": bg.get("checkpoint"), "threshold": bg.get("threshold"),
        "validation": bg.get("validation"), "test": bg.get("test"),
        "source": "ml/reports/bigan_eval_bigan_v2_h2.json"}
    D["reports"] = {"network": load_json("telemetry_step2_network.json"),
                    "tables": (load_json("telemetry_step2_tables.json") or {}).get("totals"),
                    "probe": (load_json("telemetry_step2_tables.json") or {}).get("trust_probe"),
                    "stage1": _pick(load_json("telemetry_step2_stage1.json")),
                    "stage2": _pick(load_json("telemetry_step2_stage2.json")),
                    "ctrl0": _pick(load_json("telemetry_step2_ctrl0.json")),
                    "stage1v2": _pick(load_json("telemetry_step2_stage1v2.json"))}
    return D


def _pick(ev):
    if not ev:
        return None
    return {k: ev.get(k) for k in ("all_valid", "repeat_checked", "repeat_all_identical",
                                   "passive_checked", "passive_all_identical", "forward_check",
                                   "pooled")}


def main(argv=None):
    out_dir = os.path.join(ROOT, "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    D = build(latest_only=True)
    active = D["active_configs"]
    required = ("tldqn_csv_control", "tldqn_ns3gym_adaptive")
    if any(not D["runs"].get(key) for key in required):
        raise RuntimeError("Both same-build CSV control and TLDQN live-adaptive runs are required")
    D["configs"] = {key: D["configs"][key] for key in active}
    D["runs"] = {key: D["runs"][key] for key in active}
    D["nodes"] = [100]
    D["seeds"] = sorted({int(key.split("_")[1]) for runs in D["runs"].values() for key in runs})
    D = {key: D[key] for key in ("active_configs", "meta", "nodes", "seeds", "sensors",
                                   "sinks", "configs", "runs", "ai_timing")}
    payload = json.dumps(D, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    with open(os.path.join(HERE, "dashboard_soc_template.html"), encoding="utf-8") as f:
        html = f.read().replace("__DATA__", payload)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"-> {rel(path)} ({os.path.getsize(path) / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
