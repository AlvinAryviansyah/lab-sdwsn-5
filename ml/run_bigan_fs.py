#!/usr/bin/env python3
"""Run the isolated, validation-first Bi-GAN Phase 1 experiment."""

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time

import numpy as np
import torch

from bigan_features import (FEATURE_FIELDS, K_GRID,
                            PCA_VARIANCE_GRID, FieldEncoder, make_train_validation)
from bigan_model import (BiGANConfig, anomaly_from_logit, binary_metrics,
                         build_models, discriminator_logit, prevalence_adjusted,
                         score_auc, select_threshold, validate_direction)
from bigan_ids import train as train_bigan
from nslkdd_data import (DATA_DIR, TEST_FILE, TRAIN_FILE, NSLKDDPreprocessor,
                         binary_labels, read_raw)

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_ROOT = os.path.join(HERE, "checkpoints", "bigan_fs")
REPORT_ROOT = os.path.join(HERE, "reports", "bigan_fs")
SEEDS = (1, 2, 3, 4, 5)
ARCHITECTURES = (1, 2)
VARIANTS = ("B0", "B1", "B2", "V+C")
PREVALENCE = 0.10


def _json_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as stream:
        json.dump(data, stream, indent=1, allow_nan=False)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mean_sd(values):
    return {"mean": float(statistics.mean(values)),
            "sample_sd": float(statistics.stdev(values)) if len(values) > 1 else 0.0}


def _safe_run_id(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError("run-id may contain only letters, digits, dot, underscore and hyphen")


def _prepare_model_input(encoder, frame, fields, pca=None):
    X = (encoder.transform_all(frame) if fields == FEATURE_FIELDS
         else encoder.transform_fields(frame, fields))
    return pca.transform(X) if pca is not None else X


def _validation_result(E, D, X_validation, y_validation, device):
    scores = anomaly_from_logit(discriminator_logit(E, D, X_validation, device=device))
    direction = validate_direction(scores, y_validation)
    threshold = select_threshold(scores, y_validation, prevalence=PREVALENCE)
    metrics = binary_metrics(y_validation, scores > threshold["value"])
    return scores, {
        "roc_auc": score_auc(scores, y_validation),
        "direction_check": direction,
        "threshold": threshold,
        "metrics_at_validation_threshold": metrics,
        "prevalence_adjusted_at_10_percent": prevalence_adjusted(
            metrics["TPR"], metrics["FPR"], PREVALENCE),
    }


def _parameter_count(models):
    return int(sum(parameter.numel() for model in models for parameter in model.parameters()))


def _median_ms(function, repetitions=30):
    for _ in range(5):
        function()
    samples = []
    for _ in range(repetitions):
        start = time.perf_counter()
        function()
        samples.append((time.perf_counter() - start) * 1000.0)
    return float(np.median(samples))


def _measure_inference(E, D, encoder, validation_frame, fields, pca, device):
    row = validation_frame.iloc[[0]]
    X_row = _prepare_model_input(encoder, row, fields, pca)

    def model_only():
        discriminator_logit(E, D, X_row, device=device)

    def end_to_end():
        X = _prepare_model_input(encoder, row, fields, pca)
        discriminator_logit(E, D, X, device=device)

    return {"model_only_ms_per_record": _median_ms(model_only),
            "transform_plus_model_ms_per_record": _median_ms(end_to_end)}


def _train_candidate(variant, seed, n_hidden, encoder, split, fields, pca,
                     epochs, hidden, zdim, batch, lr, d_steps, device):
    X_train = _prepare_model_input(encoder, split.train, fields, pca)
    X_validation = _prepare_model_input(encoder, split.validation, fields, pca)
    config = BiGANConfig(x_dim=X_train.shape[1], z_dim=zdim, hidden=hidden,
                         n_hidden=n_hidden, epochs=epochs, batch_size=batch,
                         lr=lr, d_steps=d_steps, seed=seed)
    start = time.perf_counter()
    G, E, D, history = train_bigan(
        config, X_train[split.y_train == 0], device=device,
        log_every=10 ** 9, log_fn=lambda *_: None)
    training_seconds = time.perf_counter() - start
    score_start = time.perf_counter()
    _, validation = _validation_result(E, D, X_validation, split.y_validation, device)
    validation_seconds = time.perf_counter() - score_start
    candidate = {
        "variant": variant,
        "seed": seed,
        "n_hidden": n_hidden,
        "selected_fields": list(fields),
        "field_count": len(fields),
        "model_input_features": int(X_train.shape[1]),
        "pca_components": int(pca.n_components_) if pca is not None else None,
        "pca_retained_variance": (float(pca.explained_variance_ratio_.sum())
                                  if pca is not None else None),
        "training_seconds": training_seconds,
        "validation_scoring_seconds": validation_seconds,
        "parameter_count": _parameter_count((G, E, D)),
        "validation": validation,
    }
    return {"G": G, "E": E, "D": D, "config": config, "history": history,
            "record": candidate, "pca": pca, "fields": list(fields)}


def _candidate_score(candidate):
    score = candidate["record"]["validation"]["roc_auc"]
    return float(score) if np.isfinite(score) else -np.inf


def _choose(candidates, size_key):
    """Maximize raw validation AUC; exact ties select the smaller representation."""
    return max(candidates, key=lambda item: (_candidate_score(item),
                                              -item["record"][size_key]))


def _save_selected(run_id, seed, n_hidden, candidate, encoder, selection,
                   search_seconds, device):
    variant = candidate["record"]["variant"]
    target = os.path.join(CHECKPOINT_ROOT, run_id, f"seed_{seed}",
                          f"hidden_{n_hidden}", variant)
    os.makedirs(target, exist_ok=False)
    torch.save({name: model.state_dict() for name, model in
                (("G", candidate["G"]), ("E", candidate["E"]), ("D", candidate["D"]))},
               os.path.join(target, "model.pt"))
    encoder.preprocessor.save(os.path.join(target, "preprocessor"))
    schema_path = os.path.join(target, "feature_schema.json")
    encoder.save_schema(schema_path, candidate["fields"], variant,
                        candidate["pca"], selection)
    if candidate["pca"] is not None:
        os.replace(os.path.splitext(schema_path)[0] + "_pca.npz",
                   os.path.join(target, "pca.npz"))
    with open(os.path.join(target, "train_log.json"), "w") as stream:
        json.dump(candidate["history"], stream, indent=1)

    inference = _measure_inference(candidate["E"], candidate["D"], encoder,
                                   candidate["validation_frame"], candidate["fields"],
                                   candidate["pca"], device)
    model_path = os.path.join(target, "model.pt")
    record = dict(candidate["record"])
    record["selection"] = selection
    record["timing"] = {
        "selected_training_seconds": record["training_seconds"],
        "search_training_seconds": float(search_seconds),
        **inference,
    }
    record["model"] = {
        "parameter_count": record["parameter_count"],
        "model_file_bytes": os.path.getsize(model_path),
    }
    config = {
        "format_version": 1,
        "variant": variant,
        "seed": seed,
        "n_hidden": n_hidden,
        "model": candidate["config"].to_dict(),
        "score": {"name": "neg_logit_discriminator_pair",
                  "direction": "malicious_if_score_above_threshold"},
        "threshold": record["validation"]["threshold"],
        "validation": record["validation"],
        "selection": selection,
        "feature_schema": "feature_schema.json",
        "preprocessor_schema_hash": encoder.preprocessor.schema_hash,
        "model_file_bytes": os.path.getsize(model_path),
        "parameter_count": record["parameter_count"],
        "timing": record["timing"],
    }
    _json_write(os.path.join(target, "inference_config.json"), config)
    record["checkpoint"] = os.path.relpath(target, CHECKPOINT_ROOT)
    record["checkpoint_bundle_bytes"] = sum(
        os.path.getsize(os.path.join(root, name))
        for root, _, files in os.walk(target) for name in files)
    return record


def train_experiment(args):
    _safe_run_id(args.run_id)
    checkpoint_dir = os.path.join(CHECKPOINT_ROOT, args.run_id)
    report_dir = os.path.join(REPORT_ROOT, args.run_id)
    if os.path.exists(checkpoint_dir) or os.path.exists(report_dir):
        raise FileExistsError(f"run already exists; choose a new --run-id: {args.run_id}")
    os.makedirs(checkpoint_dir)
    os.makedirs(report_dir)
    training_report = {
        "run_id": args.run_id,
        "status": "running",
        "dataset": "KDDTrain+ only; KDDTest+ not opened by train command",
        "kdd_train_sha256": _sha256(os.path.join(args.data_dir, TRAIN_FILE)),
        "seeds": args.seeds,
        "n_hidden": args.n_hidden,
        "variants": list(VARIANTS),
        "training_config": {"epochs": args.epochs, "hidden": args.hidden,
                            "z_dim": args.zdim, "batch_size": args.batch,
                            "learning_rate": args.lr, "d_steps": args.d_steps,
                            "device": args.device},
        "search_config": {"mi_field_counts": list(K_GRID),
                          "pca_variance_targets": list(PCA_VARIANCE_GRID),
                          "label_free_correlation_threshold": 0.95,
                          "candidate_trainings": len(args.seeds) * len(args.n_hidden) *
                          (1 + len(K_GRID) + len(PCA_VARIANCE_GRID) + 1)},
        "prevalence": PREVALENCE,
        "per_seed_models": [],
    }
    search_records = []
    all_started = time.perf_counter()

    for seed in args.seeds:
        split = make_train_validation(seed, data_dir=args.data_dir)
        encoder = FieldEncoder().fit(split.train, split.y_train)
        train_fields = encoder.rank_mutual_information(split.train, split.y_train, seed)
        ranked_fields = encoder.rank_fields(train_fields)
        control_fields, control_info = encoder.variance_correlation_control(split.train)
        seed_dir = os.path.join(checkpoint_dir, f"seed_{seed}")
        os.makedirs(seed_dir)
        np.savez(os.path.join(seed_dir, "split_indices.npz"),
                 train_indices=split.train_indices,
                 validation_indices=split.validation_indices, seed=seed)

        for n_hidden in args.n_hidden:
            arch_start = time.perf_counter()
            selected_records = []

            # B0: unselected 41-field representation.
            b0_start = time.perf_counter()
            b0 = _train_candidate("B0", seed, n_hidden, encoder, split,
                                  FEATURE_FIELDS, None, args.epochs, args.hidden,
                                  args.zdim, args.batch, args.lr, args.d_steps, args.device)
            b0_search_seconds = time.perf_counter() - b0_start
            b0["validation_frame"] = split.validation
            selected_records.append(_save_selected(
                args.run_id, seed, n_hidden, b0, encoder,
                {"method": "all_original_fields"}, b0_search_seconds, args.device))

            # B1: train-fold supervised MI search over whole original fields.
            b1_candidates = []
            b1_search_start = time.perf_counter()
            for k in K_GRID:
                fields = ranked_fields[:k]
                candidate = _train_candidate("B1", seed, n_hidden, encoder, split,
                                             fields, None, args.epochs, args.hidden,
                                             args.zdim, args.batch, args.lr,
                                             args.d_steps, args.device)
                candidate["validation_frame"] = split.validation
                candidate["record"]["candidate_k"] = k
                candidate["record"]["mi_scores"] = train_fields
                b1_candidates.append(candidate)
            b1_search_seconds = time.perf_counter() - b1_search_start
            b1 = _choose(b1_candidates, "field_count")
            for item in b1_candidates:
                item["record"]["selected"] = item is b1
                search_records.append(item["record"])
            b1_selection = {"method": "mutual_information", "candidate_field_counts": list(K_GRID),
                            "selected_field_count": b1["record"]["field_count"],
                            "ranked_fields": ranked_fields, "mi_scores": train_fields}
            selected_records.append(_save_selected(
                args.run_id, seed, n_hidden, b1, encoder, b1_selection,
                b1_search_seconds, args.device))

            # B2: PCA candidates on B1's selected fields; PCA fits normal train rows only.
            b2_candidates = []
            b2_search_start = time.perf_counter()
            for retained_variance in PCA_VARIANCE_GRID:
                pca = encoder.fit_pca(split.train, split.y_train, b1["fields"],
                                      retained_variance)
                candidate = _train_candidate("B2", seed, n_hidden, encoder, split,
                                             b1["fields"], pca, args.epochs,
                                             args.hidden, args.zdim, args.batch,
                                             args.lr, args.d_steps, args.device)
                candidate["validation_frame"] = split.validation
                candidate["record"]["pca_variance_target"] = retained_variance
                b2_candidates.append(candidate)
            b2_search_seconds = time.perf_counter() - b2_search_start
            b2 = _choose(b2_candidates, "model_input_features")
            for item in b2_candidates:
                item["record"]["selected"] = item is b2
                search_records.append(item["record"])
            b2_selection = {"method": "mutual_information_then_pca",
                            "mi_selected_fields": b1["fields"],
                            "pca_variance_candidates": list(PCA_VARIANCE_GRID),
                            "selected_pca_variance": b2["record"]["pca_variance_target"],
                            "selected_component_count": b2["record"]["pca_components"],
                            "mi_scores": train_fields}
            selected_records.append(_save_selected(
                args.run_id, seed, n_hidden, b2, encoder, b2_selection,
                b2_search_seconds, args.device))

            # V+C: one label-free train-fold pruning pass, no validation search.
            control_start = time.perf_counter()
            control = _train_candidate("V+C", seed, n_hidden, encoder, split,
                                       control_fields, None, args.epochs,
                                       args.hidden, args.zdim, args.batch,
                                       args.lr, args.d_steps, args.device)
            control_search_seconds = time.perf_counter() - control_start
            control["validation_frame"] = split.validation
            control_selection = {"method": "label_free_variance_correlation",
                                 "details": control_info,
                                 "selected_field_count": len(control_fields)}
            selected_records.append(_save_selected(
                args.run_id, seed, n_hidden, control, encoder, control_selection,
                control_search_seconds, args.device))

            arch_elapsed = time.perf_counter() - arch_start
            for record in selected_records:
                record["seed_arch_search_wall_seconds"] = arch_elapsed
            training_report["per_seed_models"].extend(selected_records)
            training_report["status"] = "running"
            search_records.extend([b0["record"], control["record"]])
            _json_write(os.path.join(report_dir, "training.json"), training_report)
            _json_write(os.path.join(report_dir, "validation_search.json"),
                        {"run_id": args.run_id, "candidates": search_records})
            print(f"seed={seed} hidden={n_hidden}: B0/B1/B2/V+C tersimpan; "
                  f"B1 k={b1['record']['field_count']}, "
                  f"B2={b2['record']['pca_components']} komponen")

    training_report["status"] = "complete"
    training_report["total_wall_seconds"] = time.perf_counter() - all_started
    _json_write(os.path.join(report_dir, "training.json"), training_report)
    _json_write(os.path.join(report_dir, "validation_search.json"),
                {"run_id": args.run_id, "candidates": search_records})
    print(f"Training/validation report -> {os.path.relpath(os.path.join(report_dir, 'training.json'), HERE)}")
    return 0


def _load_selected_model(checkpoint_dir, device):
    with open(os.path.join(checkpoint_dir, "inference_config.json")) as stream:
        config = json.load(stream)
    with open(os.path.join(checkpoint_dir, "feature_schema.json")) as stream:
        schema = json.load(stream)
    encoder = FieldEncoder()
    encoder.preprocessor = NSLKDDPreprocessor.load(
        os.path.join(checkpoint_dir, "preprocessor"))
    if encoder.preprocessor.schema_hash != config["preprocessor_schema_hash"]:
        raise ValueError(f"{checkpoint_dir}: preprocessor hash mismatch")
    encoder.field_columns = {key: [int(index) for index in values]
                             for key, values in schema["field_columns"].items()}
    encoder.column_names = schema["encoded_feature_names"]
    pca = None
    pca_path = os.path.join(checkpoint_dir, "pca.npz")
    if os.path.exists(pca_path):
        pca = dict(np.load(pca_path))
    model_config = BiGANConfig.from_dict(config["model"])
    G, E, D = build_models(model_config)
    state = torch.load(os.path.join(checkpoint_dir, "model.pt"),
                       map_location=device, weights_only=True)
    G.load_state_dict(state["G"])
    E.load_state_dict(state["E"])
    D.load_state_dict(state["D"])
    for model in (G, E, D):
        model.to(device).eval()
    return config, schema, encoder, G, E, D, pca


def _transform_saved(encoder, frame, fields, pca):
    X = encoder.transform_fields(frame, fields)
    if pca is not None:
        X = (X - pca["mean"]) @ pca["components"].T
    return X


def _test_attack_recall(test_frame, y_test, prediction, train_attack_types):
    recalls = {}
    labels = test_frame["label"].astype(str).to_numpy()
    for attack_type in sorted(set(labels[y_test == 1])):
        mask = labels == attack_type
        recalls[attack_type] = {
            "count": int(mask.sum()),
            "recall": float(prediction[mask].mean()),
            "absent_from_train_fold": attack_type not in train_attack_types,
        }
    return recalls


def evaluate_test(args):
    _safe_run_id(args.run_id)
    checkpoint_dir = os.path.join(CHECKPOINT_ROOT, args.run_id)
    report_dir = os.path.join(REPORT_ROOT, args.run_id)
    training_path = os.path.join(report_dir, "training.json")
    final_path = os.path.join(report_dir, "final_test.json")
    if not os.path.exists(training_path):
        raise FileNotFoundError(f"training report not found: {training_path}")
    if os.path.exists(final_path):
        raise FileExistsError(f"final test report already exists: {final_path}")
    with open(training_path) as stream:
        training = json.load(stream)
    if training["status"] != "complete":
        raise ValueError("cannot evaluate test before training/validation is complete")

    # This is the only code path in this driver that opens KDDTest+.
    test_frame = read_raw(TEST_FILE, args.data_dir)
    y_test = binary_labels(test_frame)
    report = {"run_id": args.run_id, "test_file": TEST_FILE,
              "test_sha256": _sha256(os.path.join(args.data_dir, TEST_FILE)),
              "test_rows": int(len(test_frame)), "prevalence": float(y_test.mean()),
              "models": [], "summary": {}}
    started = time.perf_counter()

    for model_record in training["per_seed_models"]:
        seed, n_hidden = model_record["seed"], model_record["n_hidden"]
        relative = model_record["checkpoint"]
        path = os.path.join(CHECKPOINT_ROOT, relative)
        config, schema, encoder, _, E, D, pca = _load_selected_model(path, args.device)
        split = make_train_validation(seed, data_dir=args.data_dir)
        train_attack_types = set(split.train.loc[split.train["label"] != "normal", "label"].astype(str))
        fields = schema["selected_fields"]
        X_test = _transform_saved(encoder, test_frame, fields, pca)
        scores = anomaly_from_logit(discriminator_logit(E, D, X_test, device=args.device))
        threshold = float(config["threshold"]["value"])
        prediction = scores > threshold
        metrics = binary_metrics(y_test, prediction)
        record = {
            "seed": seed,
            "n_hidden": n_hidden,
            "variant": model_record["variant"],
            "checkpoint": relative,
            "field_count": model_record["field_count"],
            "selected_fields": model_record["selected_fields"],
            "model_input_features": model_record["model_input_features"],
            "pca_components": model_record["pca_components"],
            "validation": model_record["validation"],
            "test": {"roc_auc": score_auc(scores, y_test),
                     "threshold_from_validation": threshold,
                     "metrics": metrics,
                     "prevalence_adjusted_at_10_percent": prevalence_adjusted(
                         metrics["TPR"], metrics["FPR"], PREVALENCE),
                     "attack_type_recall": _test_attack_recall(
                         test_frame, y_test, prediction, train_attack_types)},
            "model": model_record["model"],
            "checkpoint_bundle_bytes": model_record["checkpoint_bundle_bytes"],
            "timing": model_record["timing"],
        }
        report["models"].append(record)
        print(f"seed={seed} hidden={n_hidden} {record['variant']}: "
              f"test AUC={record['test']['roc_auc']:.4f}, "
              f"direction={'pass' if record['validation']['direction_check']['ok'] else 'FAIL'}")

    metric_names = ("roc_auc", "accuracy", "precision", "recall", "FPR", "F1")
    for variant in VARIANTS:
        for n_hidden in args.n_hidden:
            rows = [row for row in report["models"]
                    if row["variant"] == variant and row["n_hidden"] == n_hidden]
            if not rows:
                continue
            values = {
                "validation_direction_passes": sum(
                    bool(row["validation"]["direction_check"]["ok"]) for row in rows),
                "count": len(rows),
            }
            for dataset in ("validation", "test"):
                dataset_metrics = []
                for row in rows:
                    metric_block = (row["validation"]["metrics_at_validation_threshold"]
                                    if dataset == "validation" else row["test"]["metrics"])
                    dataset_metrics.append({
                        "roc_auc": (row["validation"]["roc_auc"] if dataset == "validation"
                                    else row["test"]["roc_auc"]),
                        **{metric: metric_block[metric] for metric in metric_names[1:]},
                    })
                values[dataset] = {
                    metric: _mean_sd([item[metric] for item in dataset_metrics])
                    for metric in metric_names}
            for metric, getter in (
                    ("field_count", lambda row: row["field_count"]),
                    ("model_input_features", lambda row: row["model_input_features"]),
                    ("parameter_count", lambda row: row["model"]["parameter_count"]),
                    ("model_file_bytes", lambda row: row["model"]["model_file_bytes"]),
                    ("checkpoint_bundle_bytes", lambda row: row["checkpoint_bundle_bytes"]),
                    ("selected_training_seconds", lambda row: row["timing"]["selected_training_seconds"]),
                    ("search_training_seconds", lambda row: row["timing"]["search_training_seconds"]),
                    ("model_only_ms_per_record", lambda row: row["timing"]["model_only_ms_per_record"]),
                    ("transform_plus_model_ms_per_record",
                     lambda row: row["timing"]["transform_plus_model_ms_per_record"])):
                values[metric] = _mean_sd([getter(row) for row in rows])
            pca_rows = [row["pca_components"] for row in rows
                        if row["pca_components"] is not None]
            if pca_rows:
                values["pca_components"] = _mean_sd(pca_rows)
            report["summary"][f"{variant}/hidden_{n_hidden}"] = values
    report["evaluation_wall_seconds"] = time.perf_counter() - started
    _json_write(final_path, report)
    _write_markdown(report, os.path.join(report_dir, "final_test.md"))
    print(f"Final test report -> {os.path.relpath(final_path, HERE)}")
    return 0


def _write_markdown(report, path):
    lines = ["# Bi-GAN Phase 1: Final Test Evaluation", "",
             f"Run: `{report['run_id']}`; test rows: {report['test_rows']}; "
             f"test prevalence: {report['prevalence']:.4f}.", "",
             "KDDTest+ was opened only by the final-evaluation command. No minimum "
             "performance threshold was imposed.", "",
             "## Per-model results", "",
             "| Seed | Hidden | Variant | Fields | Inputs | PCA | Val AUC | Val F1 | Direction | "
             "Test AUC | Test Acc | Precision | Recall | FPR | F1 | Params | Model MB | "
             "Train s | Search s | Model ms/record | End-to-end ms/record |",
             "|---:|---:|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["models"]:
        val_auc = row["validation"]["roc_auc"]
        val_metrics = row["validation"]["metrics_at_validation_threshold"]
        test = row["test"]
        metrics = test["metrics"]
        lines.append(
            f"| {row['seed']} | {row['n_hidden']} | {row['variant']} | "
            f"{row['field_count']} | {row['model_input_features']} | "
            f"{row['pca_components'] if row['pca_components'] is not None else '-'} | "
            f"{val_auc:.4f} | {val_metrics['F1']:.4f} | "
            f"{'PASS' if row['validation']['direction_check']['ok'] else 'FAIL'} | "
            f"{test['roc_auc']:.4f} | {metrics['accuracy']:.4f} | "
            f"{metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['FPR']:.4f} | {metrics['F1']:.4f} | "
            f"{row['model']['parameter_count']} | "
            f"{row['model']['model_file_bytes'] / (1024 * 1024):.3f} | "
            f"{row['timing']['selected_training_seconds']:.2f} | "
            f"{row['timing']['search_training_seconds']:.2f} | "
            f"{row['timing']['model_only_ms_per_record']:.4f} | "
            f"{row['timing']['transform_plus_model_ms_per_record']:.4f} |")
    lines += ["", "## Mean and sample standard deviation", "",
              "| Variant / hidden | Direction passes | Val AUC | Test AUC | Test Acc | Test F1 | "
              "Fields | Inputs | PCA components | Params | Train s | Search s | Infer ms/record |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, summary in report["summary"].items():
        def fmt(name, digits=3, dataset=None):
            item = summary[dataset][name] if dataset else summary[name]
            return f"{item['mean']:.{digits}f} +/- {item['sample_sd']:.{digits}f}"

        pca = fmt("pca_components", 2) if "pca_components" in summary else "-"
        lines.append(
            f"| {key} | {summary['validation_direction_passes']}/{summary['count']} | "
            f"{fmt('roc_auc', 4, 'validation')} | {fmt('roc_auc', 4, 'test')} | "
            f"{fmt('accuracy', 4, 'test')} | {fmt('F1', 4, 'test')} | "
            f"{fmt('field_count', 2)} | {fmt('model_input_features', 2)} | {pca} | "
            f"{fmt('parameter_count', 0)} | {fmt('selected_training_seconds', 2)} | "
            f"{fmt('search_training_seconds', 2)} | {fmt('transform_plus_model_ms_per_record', 4)} |")
    with open(path, "w") as stream:
        stream.write("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    train_parser = subparsers.add_parser("train", help="fit/search using KDDTrain+ only")
    train_parser.add_argument("--run-id", required=True)
    train_parser.add_argument("--data-dir", default=DATA_DIR)
    train_parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    train_parser.add_argument("--n-hidden", type=int, nargs="+", default=list(ARCHITECTURES))
    train_parser.add_argument("--epochs", type=int, default=20)
    train_parser.add_argument("--hidden", type=int, default=128)
    train_parser.add_argument("--zdim", type=int, default=32)
    train_parser.add_argument("--batch", type=int, default=256)
    train_parser.add_argument("--lr", type=float, default=2e-4)
    train_parser.add_argument("--d-steps", type=int, default=1)
    train_parser.add_argument("--device", default="cpu")
    test_parser = subparsers.add_parser("evaluate-test", help="one final KDDTest+ evaluation")
    test_parser.add_argument("--run-id", required=True)
    test_parser.add_argument("--data-dir", default=DATA_DIR)
    test_parser.add_argument("--n-hidden", type=int, nargs="+", default=list(ARCHITECTURES))
    test_parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    if args.command == "train":
        if not args.seeds or not args.n_hidden or any(h not in ARCHITECTURES for h in args.n_hidden):
            parser.error("seeds and n-hidden must be non-empty; supported n_hidden values are 1 and 2")
        return train_experiment(args)
    return evaluate_test(args)


if __name__ == "__main__":
    sys.exit(main())