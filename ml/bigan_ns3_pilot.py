#!/usr/bin/env python3
"""Bi-GAN pilot on trace-derived NS-3 telemetry; no labels enter model inputs."""

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
import time

import numpy as np
import torch
from sklearn.preprocessing import StandardScaler

from bigan_ids import train as train_bigan
from bigan_model import (BiGANConfig, anomaly_from_logit, binary_metrics,
                         build_models, discriminator_logit, score_auc)
from export_routes import main as export_routes
from telemetry_schema import load_links, load_nodes, paths as telemetry_paths

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CHECKPOINT_ROOT = os.path.join(HERE, "checkpoints", "bigan_ns3_pilot")
REPORT_ROOT = os.path.join(HERE, "reports", "bigan_ns3_pilot")
PREDICTION_COLUMNS = ["node_id", "score", "threshold", "pred_intrusion"]
CPP_DECISION_COLUMNS = ["node_id", "actual_mal", "anomaly_score", "threshold",
                        "pred_intrusion"]
CPP_WINDOW_COLUMNS = ["node_id", "actual_mal", "p0"]
FEATURE_SCHEMA_VERSION = 2
CALIBRATION_FPR = 0.05

# Only values exported from packet/radio traces and passive peer observation are used.
# Self-forward/drop counters are excluded because they expose simulator internals and
# can reveal the grayhole implementation directly.
FEATURE_NAMES = [
    "origin_packets", "origin_bytes", "mean_origin_packet_bytes",
    "ip_received_packets", "ip_local_packets",
    "mac_acked", "mac_nacked", "mac_retry_drops", "mac_other_drops",
    "mac_response_timeouts", "phy_tx_mpdu", "phy_tx_bytes", "mean_phy_tx_bytes",
    "phy_rx_ok_mpdu", "phy_rx_failed_mpdu", "phy_rx_dropped_mpdu",
    "watch_started_as_observer", "observed_watches", "observed_forwarded",
    "observed_forwarded_late", "observed_unobserved_rxfail",
    "observed_unobserved_clean", "observed_neighbor_count", "observed_rx_ok_mpdu",
    "observed_mac_acked", "observed_mac_nacked", "observed_mac_retry_drops",
    "observed_mac_other_drops", "observed_ack_timeouts", "observed_mean_rssi_dbm",
    "observed_mean_snr_db", "observed_mean_forward_delay_s",
]
LOG1P_FEATURES = {
    "origin_packets", "origin_bytes", "ip_received_packets", "ip_local_packets",
    "mac_acked", "mac_nacked", "mac_retry_drops", "mac_other_drops",
    "mac_response_timeouts", "phy_tx_mpdu", "phy_tx_bytes", "phy_rx_ok_mpdu",
    "phy_rx_failed_mpdu", "phy_rx_dropped_mpdu", "watch_started_as_observer",
    "observed_watches", "observed_forwarded", "observed_forwarded_late",
    "observed_unobserved_rxfail", "observed_unobserved_clean",
    "observed_neighbor_count", "observed_rx_ok_mpdu", "observed_mac_acked",
    "observed_mac_nacked", "observed_mac_retry_drops", "observed_mac_other_drops",
    "observed_ack_timeouts",
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as stream:
        json.dump(value, stream, indent=1, allow_nan=False)


def _read_scenario_labels(path, n):
    labels = np.full(n, -1, dtype=np.int64)
    with open(path, newline="") as stream:
        for row in csv.DictReader(stream):
            node = int(row["node_id"])
            if not 0 <= node < n or labels[node] != -1:
                raise ValueError(f"{path}: invalid/duplicate node_id {node}")
            labels[node] = int(row["actual_mal"] != "0")
    if (labels < 0).any():
        raise ValueError(f"{path}: expected labels for every node 0..{n - 1}")
    return labels


def _feature_row(node, observed):
    origin_packets = float(node["self_ip_orig_pkts"])
    origin_bytes = float(node["self_ip_orig_bytes"])
    phy_tx = float(node["self_phy_tx_mpdu"])
    phy_bytes = float(node["self_phy_tx_bytes"])
    values = {
        "origin_packets": origin_packets,
        "origin_bytes": origin_bytes,
        "mean_origin_packet_bytes": origin_bytes / origin_packets if origin_packets else 0.0,
        "ip_received_packets": float(node["self_ip_rx_pkts"]),
        "ip_local_packets": float(node["self_ip_local_pkts"]),
        "mac_acked": float(node["self_mac_acked"]),
        "mac_nacked": float(node["self_mac_nacked"]),
        "mac_retry_drops": float(node["self_mac_drop_retry"]),
        "mac_other_drops": float(node["self_mac_drop_other"]),
        "mac_response_timeouts": float(node["self_mac_ack_timeout"]),
        "phy_tx_mpdu": phy_tx,
        "phy_tx_bytes": phy_bytes,
        "mean_phy_tx_bytes": phy_bytes / phy_tx if phy_tx else 0.0,
        "phy_rx_ok_mpdu": float(node["self_phy_rx_ok_mpdu"]),
        "phy_rx_failed_mpdu": float(node["self_phy_rx_fail_mpdu"]),
        "phy_rx_dropped_mpdu": float(node["self_phy_rx_drop"]),
        "watch_started_as_observer": float(node["wd_started_as_observer"]),
        "observed_watches": float(observed["wd_started"]),
        "observed_forwarded": float(observed["wd_forwarded"]),
        "observed_forwarded_late": float(observed["wd_forwarded_late"]),
        "observed_unobserved_rxfail": float(observed["wd_unobserved_rxfail"]),
        "observed_unobserved_clean": float(observed["wd_unobserved_clean"]),
        "observed_neighbor_count": float(observed["neighbor_count"]),
        "observed_rx_ok_mpdu": float(observed["rx_ok_from"]),
        "observed_mac_acked": float(observed["mac_handoff_acked"]),
        "observed_mac_nacked": float(observed["mac_handoff_nacked"]),
        "observed_mac_retry_drops": float(observed["mac_handoff_drop_retry"]),
        "observed_mac_other_drops": float(observed["mac_handoff_drop_other"]),
        "observed_ack_timeouts": float(observed["mac_ack_timeout"]),
        "observed_mean_rssi_dbm": observed["rssi_mean_dbm"],
        "observed_mean_snr_db": observed["snr_mean_db"],
        "observed_mean_forward_delay_s": observed["wd_delay_mean_s"],
    }
    return np.asarray([values[name] for name in FEATURE_NAMES], dtype=np.float64)


def extract_window(telem_dir, n, seed, window=0):
    """Build label-free per-sensor packet/radio features from existing NS-3 traces."""
    p = telemetry_paths(telem_dir, n, seed)
    nodes = {row["node_id"]: row for row in load_nodes(p["node"])
             if row["window"] == window}
    if set(nodes) != set(range(n)):
        raise ValueError(f"{p['node']}: expected exactly one node row in window {window}")

    observed = {i: {
        "wd_started": 0, "wd_forwarded": 0, "wd_forwarded_late": 0,
        "wd_unobserved_rxfail": 0, "wd_unobserved_clean": 0,
        "neighbor_count": 0, "rx_ok_from": 0,
        "mac_handoff_acked": 0, "mac_handoff_nacked": 0,
        "mac_handoff_drop_retry": 0, "mac_handoff_drop_other": 0,
        "mac_ack_timeout": 0, "rssi_weighted": 0.0, "snr_weighted": 0.0,
        "rx_weight": 0, "delay_weighted": 0.0, "delay_weight": 0,
    } for i in range(n)}
    observers = {i: set() for i in range(n)}
    for row in load_links(p["links"]):
        if row["window"] != window or row["neighbor_type"] != "sensor":
            continue
        target = row["neighbor_id"]
        if target not in observed:
            raise ValueError(f"{p['links']}: invalid neighbor_id {target}")
        bucket = observed[target]
        observers[target].add(row["observer"])
        for column in ("wd_started", "wd_forwarded", "wd_forwarded_late",
                       "wd_unobserved_rxfail", "wd_unobserved_clean", "rx_ok_from",
                       "mac_handoff_acked", "mac_handoff_nacked",
                       "mac_handoff_drop_retry", "mac_handoff_drop_other",
                       "mac_ack_timeout"):
            bucket[column] += row[column]
        rx_count = row["rx_ok_from"]
        if rx_count and np.isfinite(row["rssi_mean_dbm"]):
            bucket["rssi_weighted"] += row["rssi_mean_dbm"] * rx_count
            bucket["snr_weighted"] += row["snr_mean_db"] * rx_count
            bucket["rx_weight"] += rx_count
        delay_count = row["wd_forwarded"] + row["wd_forwarded_late"]
        if delay_count and np.isfinite(row["wd_delay_mean_s"]):
            bucket["delay_weighted"] += row["wd_delay_mean_s"] * delay_count
            bucket["delay_weight"] += delay_count

    records = []
    for node_id in range(n):
        bucket = observed[node_id]
        bucket["neighbor_count"] = len(observers[node_id])
        bucket["rssi_dbm"] = (bucket["rssi_weighted"] / bucket["rx_weight"]
                              if bucket["rx_weight"] else 0.0)
        bucket["snr_db"] = (bucket["snr_weighted"] / bucket["rx_weight"]
                            if bucket["rx_weight"] else 0.0)
        bucket["wd_delay_mean_s"] = (bucket["delay_weighted"] / bucket["delay_weight"]
                                     if bucket["delay_weight"] else 0.0)
        bucket["rssi_mean_dbm"] = bucket["rssi_dbm"]
        bucket["snr_mean_db"] = bucket["snr_db"]
        records.append({"node_id": node_id, "window": window,
                        "features": _feature_row(nodes[node_id], bucket)})
    return records, p


def _matrix(records):
    if not records:
        raise ValueError("no feature records")
    return np.vstack([record["features"] for record in records]).astype(np.float32)


def _model_matrix(records):
    matrix = _matrix(records)
    indices = [index for index, name in enumerate(FEATURE_NAMES) if name in LOG1P_FEATURES]
    matrix[:, indices] = np.log1p(matrix[:, indices])
    return matrix


def _write_feature_csv(path, records):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["node_id", "window"] + FEATURE_NAMES)
        for row in records:
            writer.writerow([row["node_id"], row["window"]] +
                            [f"{value:.10g}" for value in row["features"]])


def _read_predictions(path, n):
    predictions = np.full(n, -1, dtype=np.int64)
    scores = np.full(n, np.nan, dtype=np.float64)
    thresholds = np.full(n, np.nan, dtype=np.float64)
    with open(path, newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != PREDICTION_COLUMNS:
            raise ValueError(f"{path}: prediction header mismatch")
        for row in reader:
            node = int(row["node_id"])
            if not 0 <= node < n or predictions[node] != -1:
                raise ValueError(f"{path}: invalid/duplicate node_id {node}")
            predictions[node] = int(row["pred_intrusion"])
            scores[node] = float(row["score"])
            thresholds[node] = float(row["threshold"])
    if (predictions < 0).any() or not np.isfinite(scores).all() or not np.isfinite(thresholds).all():
        raise ValueError(f"{path}: predictions are incomplete or non-finite")
    return predictions.astype(bool), scores, thresholds


def _write_scenario_inputs(path, labels, scores, thresholds, predictions):
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(CPP_DECISION_COLUMNS)
        for node, actual in enumerate(labels):
            writer.writerow([node, int(actual), f"{scores[node]:.10g}",
                             f"{thresholds[node]:.10g}", int(predictions[node])])


CPP_DECISION_COLUMNS = ["node_id", "actual_mal", "anomaly_score", "threshold",
                        "pred_intrusion"]
CPP_WINDOW_COLUMNS = ["node_id", "actual_mal", "p0"]


def _write_window_inputs(path, labels, predictions):
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(CPP_WINDOW_COLUMNS)
        for node, actual in enumerate(labels):
            writer.writerow([node, int(actual), int(predictions[node])])


def _write_hybrid(path, predictions):
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(DECISION_COLUMNS)
        for node, pred in enumerate(predictions):
            # F2: Bi-GAN contributes an alarm only; no node is automatically isolated.
            writer.writerow([node, "normal", int(pred), 0, "none"])


def prepare_scenarios(args):
    if os.path.exists(args.out_dir):
        raise FileExistsError(f"pilot input directory exists: {args.out_dir}")
    scenario_dir = os.path.join(args.out_dir, "scenarios")
    route_dir = os.path.join(args.out_dir, "routes")
    os.makedirs(scenario_dir)
    os.makedirs(route_dir)
    seeds = list(args.clean_seeds) + list(args.eval_seeds)
    if len(set(seeds)) != len(seeds):
        raise ValueError("clean and evaluation seeds must be distinct")
    for seed in args.clean_seeds:
        labels = np.zeros(args.nodes, dtype=np.int64)
        _write_scenario_inputs(os.path.join(scenario_dir,
                             f"bigan_decisions_{args.nodes}_s{seed}.csv"),
                              labels, np.zeros(args.nodes), np.zeros(args.nodes),
                              np.zeros(args.nodes, dtype=bool))
        _write_window_inputs(os.path.join(scenario_dir,
                            f"bigan_windows_{args.nodes}_s{seed}.csv"),
                             labels, np.zeros(args.nodes, dtype=bool))
    for seed in args.eval_seeds:
        source = os.path.join(args.source_scenario_dir,
                              f"bigan_decisions_{args.nodes}_s{seed}.csv")
        labels = _read_scenario_labels(source, args.nodes)
        _write_scenario_inputs(os.path.join(scenario_dir,
                             f"bigan_decisions_{args.nodes}_s{seed}.csv"),
                              labels, np.zeros(args.nodes), np.zeros(args.nodes),
                              np.zeros(args.nodes, dtype=bool))
        _write_window_inputs(os.path.join(scenario_dir,
                            f"bigan_windows_{args.nodes}_s{seed}.csv"),
                             labels, np.zeros(args.nodes, dtype=bool))

    export_routes(["--nodes", str(args.nodes), "--seeds", *map(str, seeds),
                   "--scenario-dir", scenario_dir, "--out-dir", route_dir,
                   "--trust-source", "none"])
    _write_json(os.path.join(args.out_dir, "pilot_inputs.json"), {
        "nodes": args.nodes,
        "clean_seeds": list(args.clean_seeds),
        "calibration_seed": args.calibration_seed,
        "evaluation_seeds": list(args.eval_seeds),
        "scenario_dir": scenario_dir,
        "route_dir": route_dir,
        "routes_use_label_free_trust": True,
        "clean_scenario_ground_truth": "all nodes normal; controls simulated behavior only",
    })
    print(f"Pilot inputs -> {args.out_dir}")
    return 0
def train_pilot(args):
    run_dir = os.path.join(args.checkpoint_root, args.run_id)
    report_dir = os.path.join(args.report_root, args.run_id)
    if os.path.exists(run_dir) or os.path.exists(report_dir):
        raise FileExistsError(f"pilot run exists; choose a new run-id: {args.run_id}")
    if args.calibration_seed in args.train_seeds:
        raise ValueError("calibration seed must be held out from training")
    train_records, source_hashes = [], []
    for seed in args.train_seeds:
        records, file_paths = extract_window(args.telem_dir, args.nodes, seed, args.window)
        train_records.extend(records)
        source_hashes.extend(sha256(file_paths[key]) for key in ("node", "links"))
    calibration_records, calibration_paths = extract_window(
        args.telem_dir, args.nodes, args.calibration_seed, args.window)
    calibration_hashes = {key: sha256(calibration_paths[key]) for key in ("node", "links")}

    X_train_raw = _model_matrix(train_records)
    X_calibration_raw = _model_matrix(calibration_records)
    scaler = StandardScaler().fit(X_train_raw)
    X_train = scaler.transform(X_train_raw).astype(np.float32)
    X_calibration = scaler.transform(X_calibration_raw).astype(np.float32)
    config = BiGANConfig(x_dim=len(FEATURE_NAMES), n_hidden=1, seed=args.seed,
                         epochs=args.epochs, batch_size=args.batch,
                         hidden=args.hidden, z_dim=args.zdim, lr=args.lr)
    start = time.perf_counter()
    G, E, D, history = train_bigan(config, X_train, device=args.device,
                                   log_every=10 ** 9, log_fn=lambda *_: None)
    training_seconds = time.perf_counter() - start
    calibration_scores = anomaly_from_logit(
        discriminator_logit(E, D, X_calibration, device=args.device))
    threshold = float(np.quantile(calibration_scores, 1.0 - args.calibration_fpr))

    os.makedirs(run_dir)
    os.makedirs(report_dir)
    torch.save({name: model.state_dict() for name, model in
                (("G", G), ("E", E), ("D", D))}, os.path.join(run_dir, "model.pt"))
    np.savez(os.path.join(run_dir, "scaler.npz"), mean=scaler.mean_, scale=scaler.scale_)
    with open(os.path.join(run_dir, "train_log.json"), "w") as stream:
        json.dump(history, stream, indent=1)
    schema = {"feature_schema_version": FEATURE_SCHEMA_VERSION,
              "feature_names": FEATURE_NAMES,
              "transforms": {"counts_and_bytes": "log1p then train-fitted StandardScaler",
                             "means_and_radio_quality": "train-fitted StandardScaler"},
              "excluded": ["actual_mal", "pred_intrusion", "self_ip_fwd_*",
                           "self_ip_drop_*", "watchdog_audit", "IP/transport ports not exported"],
              "window_index": args.window,
              "window_s": args.window_s}
    _write_json(os.path.join(run_dir, "feature_schema.json"), schema)
    _write_json(os.path.join(run_dir, "inference_config.json"), {
        "format_version": 1,
        "model": config.to_dict(),
        "score": "-logit D(x, E(x)); high means more anomalous by fixed convention",
        "threshold": threshold,
        "threshold_method": "quantile of benign calibration scores only",
        "calibration_fpr_target": args.calibration_fpr,
        "feature_schema": "feature_schema.json",
    })
    _write_feature_csv(os.path.join(report_dir, "features_clean_train.csv"), train_records)
    _write_feature_csv(os.path.join(report_dir, "features_clean_calibration.csv"),
                       calibration_records)
    report = {
        "run_id": args.run_id,
        "status": "trained",
        "model": config.to_dict(),
        "training_rows": len(train_records),
        "calibration_rows": len(calibration_records),
        "training_seeds": list(args.train_seeds),
        "calibration_seed": args.calibration_seed,
        "training_feature_file_sha256": source_hashes,
        "calibration_telemetry_sha256": calibration_hashes,
        "training_seconds": training_seconds,
        "calibration_threshold": threshold,
        "calibration_empirical_fpr": float(np.mean(calibration_scores > threshold)),
        "calibration_score_min": float(calibration_scores.min()),
        "calibration_score_median": float(np.median(calibration_scores)),
        "calibration_score_max": float(calibration_scores.max()),
        "parameter_count": int(sum(p.numel() for m in (G, E, D) for p in m.parameters())),
        "model_bytes": os.path.getsize(os.path.join(run_dir, "model.pt")),
        "uses_ground_truth": False,
    }
    _write_json(os.path.join(report_dir, "training.json"), report)
    print(f"Pilot Bi-GAN trained: rows={len(train_records)} features={len(FEATURE_NAMES)} "
          f"threshold={threshold:.5f} clean calibration FPR="
          f"{report['calibration_empirical_fpr']:.3f}")
    return 0


def load_pilot(run_id, checkpoint_root=CHECKPOINT_ROOT, device="cpu"):
    run_dir = os.path.join(checkpoint_root, run_id)
    with open(os.path.join(run_dir, "inference_config.json")) as stream:
        config = json.load(stream)
    with open(os.path.join(run_dir, "feature_schema.json")) as stream:
        schema = json.load(stream)
    scaler_data = np.load(os.path.join(run_dir, "scaler.npz"))
    scaler_mean, scaler_scale = scaler_data["mean"], scaler_data["scale"]
    model_config = BiGANConfig.from_dict(config["model"])
    G, E, D = build_models(model_config)
    state = torch.load(os.path.join(run_dir, "model.pt"), map_location=device,
                       weights_only=True)
    for model, key in ((G, "G"), (E, "E"), (D, "D")):
        model.load_state_dict(state[key])
        model.to(device).eval()
    if schema["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
        raise ValueError("unsupported NS-3 feature schema version")
    return config, schema, scaler_mean, scaler_scale, E, D


def predict_pilot(args):
    config, schema, mean, scale, E, D = load_pilot(
        args.run_id, args.checkpoint_root, args.device)
    threshold_override = getattr(args, "threshold", None)
    threshold = float(config["threshold"] if threshold_override is None else threshold_override)
    if not np.isfinite(threshold):
        raise ValueError("prediction threshold must be finite")
    pipeline_start = time.perf_counter()
    records, input_paths = extract_window(args.telem_dir, args.nodes, args.seed,
                                          args.window)
    X = (_model_matrix(records) - mean) / scale
    inference_start = time.perf_counter()
    scores = anomaly_from_logit(discriminator_logit(E, D, X.astype(np.float32),
                                                     device=args.device))
    inference_ms = (time.perf_counter() - inference_start) * 1000.0
    pipeline_ms = (time.perf_counter() - pipeline_start) * 1000.0
    output = os.path.join(args.out_dir,
                          f"bigan_pilot_predictions_{args.nodes}_s{args.seed}.csv")
    if os.path.exists(output):
        raise FileExistsError(f"prediction output exists: {output}")
    os.makedirs(args.out_dir, exist_ok=True)
    predictions = scores > threshold
    with open(output, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(PREDICTION_COLUMNS)
        for row, score, pred in zip(records, scores, predictions):
            writer.writerow([row["node_id"], f"{score:.10g}", f"{threshold:.10g}",
                             int(pred)])
    _write_json(output + ".meta.json", {
        "run_id": args.run_id, "nodes": args.nodes, "seed": args.seed,
        "window": args.window, "source_features_sha256":
            {key: sha256(input_paths[key]) for key in ("node", "links")},
        "feature_schema_version": schema["feature_schema_version"],
        "contains_ground_truth": False,
        "threshold": threshold,
        "threshold_source": "checkpoint" if threshold_override is None else "override",
        "feature_extraction_ms": pipeline_ms - inference_ms,
        "model_inference_total_ms": inference_ms,
        "model_inference_ms_per_record": inference_ms / max(len(records), 1),
    })
    print(f"Predictions -> {output} ({int(predictions.sum())} alarms, no labels in input)")
    return 0


def verify_replay(args):
    rows_a, _ = extract_window(args.telem_a, args.nodes, args.seed, args.window)
    rows_b, _ = extract_window(args.telem_b, args.nodes, args.seed, args.window)
    ids_a = [row["node_id"] for row in rows_a]
    ids_b = [row["node_id"] for row in rows_b]
    X_a, X_b = _matrix(rows_a), _matrix(rows_b)
    identical = ids_a == ids_b and np.array_equal(X_a, X_b)
    diff = float(np.max(np.abs(X_a - X_b))) if X_a.shape == X_b.shape else float("inf")
    print(f"feature replay n={args.nodes} seed={args.seed} window={args.window}: "
          f"{'identical' if identical else 'MISMATCH'} max_abs_diff={diff:.10g}")
    return 0 if identical else 1


def _prediction_rows(path, n):
    predictions = np.full(n, -1, dtype=np.int64)
    scores = np.full(n, np.nan)
    thresholds = np.full(n, np.nan)
    with open(path, newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != PREDICTION_COLUMNS:
            raise ValueError(f"{path}: prediction header mismatch")
        for row in reader:
            i = int(row["node_id"])
            if not 0 <= i < n or predictions[i] != -1:
                raise ValueError(f"{path}: invalid/duplicate node_id {i}")
            predictions[i] = int(row["pred_intrusion"])
            scores[i] = float(row["score"])
            thresholds[i] = float(row["threshold"])
    if (predictions < 0).any() or not np.isfinite(scores).all() or not np.isfinite(thresholds).all():
        raise ValueError(f"{path}: prediction file incomplete")
    return predictions.astype(bool), scores, thresholds


def _confusion(y, pred):
    y, pred = np.asarray(y, bool), np.asarray(pred, bool)
    return {"TP": int(np.sum(y & pred)), "TN": int(np.sum(~y & ~pred)),
            "FP": int(np.sum(~y & pred)), "FN": int(np.sum(y & ~pred))}


def evaluate_pilot(args):
    reports = []
    aggregate = {key: 0 for key in ("TP", "TN", "FP", "FN")}
    selection_seeds = getattr(args, "selection_seeds", None)
    for seed in args.seeds:
        prediction_path = os.path.join(args.pred_dir,
            f"bigan_pilot_predictions_{args.nodes}_s{seed}.csv")
        scenario_path = os.path.join(args.scenario_dir,
            f"bigan_decisions_{args.nodes}_s{seed}.csv")
        pred, scores, thresholds = _prediction_rows(prediction_path, args.nodes)
        labels = _read_scenario_labels(scenario_path, args.nodes).astype(bool)
        c = _confusion(labels, pred)
        for key in aggregate:
            aggregate[key] += c[key]
        metrics = binary_metrics(labels, pred)
        meta_path = prediction_path + ".meta.json"
        timing = {}
        if os.path.exists(meta_path):
            with open(meta_path) as stream:
                timing = json.load(stream)
        report = {"n": args.nodes, "seed": seed, "confusion": c,
                  "metrics": metrics, "roc_auc": score_auc(scores, labels),
                  "threshold": float(thresholds[0]),
                  "alarms": int(pred.sum()), "timing": timing,
                  "labels_used_only_for_evaluation": (
                      None if selection_seeds is None else seed not in selection_seeds)}
        reports.append(report)
        print(f"n={args.nodes} seed={seed}: TP={c['TP']} FP={c['FP']} "
              f"FN={c['FN']} TN={c['TN']} P={metrics['precision']:.3f} "
              f"R={metrics['recall']:.3f} F1={metrics['F1']:.3f} "
              f"FPR={metrics['FPR']:.3f} AUC={report['roc_auc']:.3f}")
    pooled = {"confusion": aggregate, "metrics": binary_metrics(
        np.array([True] * (aggregate["TP"] + aggregate["FN"]) +
                 [False] * (aggregate["TN"] + aggregate["FP"])),
        np.array([True] * aggregate["TP"] + [False] * aggregate["FN"] +
                 [True] * aggregate["FP"] + [False] * aggregate["TN"]))}
    result = {"run_id": args.run_id, "nodes": args.nodes, "seeds": list(args.seeds),
              "per_seed": reports, "pooled": pooled,
              "threshold_selection_label_seeds": selection_seeds,
              "no_threshold_or_model_selection_on_labels": (
                  None if selection_seeds is None else False)}
    if os.path.exists(args.out):
        raise FileExistsError(f"evaluation output exists: {args.out}")
    _write_json(args.out, result)
    print(f"Pooled: TP={aggregate['TP']} FP={aggregate['FP']} "
          f"FN={aggregate['FN']} TN={aggregate['TN']} "
          f"P={pooled['metrics']['precision']:.3f} R={pooled['metrics']['recall']:.3f} "
          f"F1={pooled['metrics']['F1']:.3f} FPR={pooled['metrics']['FPR']:.3f}")
    return 0


def _write_scenario_inputs(path, labels, n):
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(CPP_DECISION_COLUMNS)
        for i in range(n):
            writer.writerow([i, int(labels[i]), 0, 0, 0])


def _write_window_input(path, labels, n):
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["node_id", "actual_mal", "p0"])
        for i in range(n):
            writer.writerow([i, int(labels[i]), 0])


def prepare_inputs(args):
    if os.path.exists(args.out_dir):
        raise FileExistsError(f"pilot input directory exists: {args.out_dir}")
    scenario_dir = os.path.join(args.out_dir, "scenarios")
    route_dir = os.path.join(args.out_dir, "routes")
    os.makedirs(scenario_dir)
    os.makedirs(route_dir)
    benign_seeds = list(args.clean_seeds) + [args.calibration_seed]
    all_seeds = benign_seeds + list(args.eval_seeds)
    if len(set(all_seeds)) != len(all_seeds):
        raise ValueError("clean and evaluation seeds must be distinct")
    for seed in benign_seeds:
        _write_scenario_inputs(os.path.join(scenario_dir,
            f"bigan_decisions_{args.nodes}_s{seed}.csv"), np.zeros(args.nodes, dtype=int), args.nodes)
        _write_window_input(os.path.join(scenario_dir,
            f"bigan_windows_{args.nodes}_s{seed}.csv"), np.zeros(args.nodes, dtype=int), args.nodes)
    for seed in args.eval_seeds:
        source = os.path.join(args.source_scenario_dir,
            f"bigan_decisions_{args.nodes}_s{seed}.csv")
        labels = _read_scenario_labels(source, args.nodes)
        _write_scenario_inputs(os.path.join(scenario_dir,
            f"bigan_decisions_{args.nodes}_s{seed}.csv"), labels, args.nodes)
        _write_window_input(os.path.join(scenario_dir,
            f"bigan_windows_{args.nodes}_s{seed}.csv"), labels, args.nodes)
    export_routes(["--nodes", str(args.nodes), "--seeds", *map(str, all_seeds),
                   "--scenario-dir", scenario_dir, "--out-dir", route_dir,
                   "--trust-source", "none"])
    _write_json(os.path.join(args.out_dir, "manifest.json"), {
        "nodes": args.nodes, "clean_seeds": list(args.clean_seeds),
        "calibration_seed": args.calibration_seed,
        "evaluation_seeds": list(args.eval_seeds),
        "scenario_dir": scenario_dir, "route_dir": route_dir,
        "route_trust_source": "none",
        "note": "GT in scenario inputs controls simulated attacker behavior only; feature extractor never reads it.",
    })
    print(f"Prepared separate pilot inputs -> {args.out_dir}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-inputs")
    prepare.add_argument("--nodes", type=int, default=100)
    prepare.add_argument("--clean-seeds", type=int, nargs="+", default=[101, 102, 103])
    prepare.add_argument("--calibration-seed", type=int, default=104)
    prepare.add_argument("--eval-seeds", type=int, nargs="+", default=[1, 2, 3])
    prepare.add_argument("--source-scenario-dir", default=os.path.join(ROOT, "ns3-sim", "results"))
    prepare.add_argument("--out-dir", default=os.path.join(ROOT, "ns3-sim", "results", "bigan_pilot"))

    extract = commands.add_parser("extract")
    extract.add_argument("--telem-dir", required=True)
    extract.add_argument("--nodes", type=int, default=100)
    extract.add_argument("--seed", type=int, required=True)
    extract.add_argument("--window", type=int, default=0)
    extract.add_argument("--out", required=True)

    train = commands.add_parser("train")
    train.add_argument("--run-id", required=True)
    train.add_argument("--telem-dir", required=True)
    train.add_argument("--nodes", type=int, default=100)
    train.add_argument("--train-seeds", type=int, nargs="+", required=True)
    train.add_argument("--calibration-seed", type=int, required=True)
    train.add_argument("--window", type=int, default=0)
    train.add_argument("--window-s", type=float, default=7.3)
    train.add_argument("--calibration-fpr", type=float, default=CALIBRATION_FPR)
    train.add_argument("--epochs", type=int, default=20)
    train.add_argument("--batch", type=int, default=256)
    train.add_argument("--hidden", type=int, default=128)
    train.add_argument("--zdim", type=int, default=32)
    train.add_argument("--lr", type=float, default=2e-4)
    train.add_argument("--seed", type=int, default=1)
    train.add_argument("--device", default="cpu")
    train.add_argument("--checkpoint-root", default=CHECKPOINT_ROOT)
    train.add_argument("--report-root", default=REPORT_ROOT)

    predict = commands.add_parser("predict")
    predict.add_argument("--run-id", required=True)
    predict.add_argument("--telem-dir", required=True)
    predict.add_argument("--nodes", type=int, default=100)
    predict.add_argument("--seed", type=int, required=True)
    predict.add_argument("--window", type=int, default=0)
    predict.add_argument("--device", default="cpu")
    predict.add_argument("--checkpoint-root", default=CHECKPOINT_ROOT)
    predict.add_argument("--threshold", type=float, default=None,
                         help="override checkpoint threshold for prediction")
    predict.add_argument("--out-dir", required=True)

    replay = commands.add_parser("verify-replay",
                                 help="require identical extracted features in runs A and B")
    replay.add_argument("--telem-a", required=True)
    replay.add_argument("--telem-b", required=True)
    replay.add_argument("--nodes", type=int, default=100)
    replay.add_argument("--seed", type=int, required=True)
    replay.add_argument("--window", type=int, default=0)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--pred-dir", required=True)
    evaluate.add_argument("--scenario-dir", required=True,
                          help="labels are read here only after prediction is produced")
    evaluate.add_argument("--nodes", type=int, default=100)
    evaluate.add_argument("--seeds", type=int, nargs="+", required=True)
    evaluate.add_argument("--selection-seeds", type=int, nargs="+", default=None,
                          help="seeds whose labels were used to select the threshold")
    evaluate.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "prepare-inputs":
        if args.calibration_seed in args.clean_seeds or args.calibration_seed in args.eval_seeds:
            parser.error("calibration seed must be distinct from train/eval seeds")
        return prepare_inputs(args)
    if args.command == "extract":
        records, _ = extract_window(args.telem_dir, args.nodes, args.seed, args.window)
        _write_feature_csv(args.out, records)
        print(f"Extracted {len(records)} label-free feature rows -> {args.out}")
        return 0
    if args.command == "train":
        if not 0.0 < args.calibration_fpr < 1.0:
            parser.error("calibration-fpr must be between 0 and 1")
        if args.calibration_seed in args.train_seeds:
            parser.error("calibration seed must be held out")
        return train_pilot(args)
    if args.command == "predict":
        return predict_pilot(args)
    if args.command == "verify-replay":
        return verify_replay(args)
    return evaluate_pilot(args)


if __name__ == "__main__":
    sys.exit(main())