#!/usr/bin/env python3
"""Train-fold-only feature selection and extraction for Bi-GAN Phase 1."""

from dataclasses import dataclass

import numpy as np
from sklearn.decomposition import PCA
from sklearn.feature_selection import mutual_info_classif
from sklearn.model_selection import train_test_split

from nslkdd_data import (CATEGORICAL, COLUMNS, DATA_DIR, NON_FEATURE, NUMERIC,
                         NSLKDDPreprocessor, TRAIN_FILE, binary_labels, read_raw)

FEATURE_FIELDS = [column for column in COLUMNS if column not in NON_FEATURE]
K_GRID = (5, 10, 15, 20, 30, 41)
PCA_VARIANCE_GRID = (0.90, 0.95, 0.99)
CORRELATION_THRESHOLD = 0.95


@dataclass
class TrainValidation:
    train: object
    y_train: np.ndarray
    validation: object
    y_validation: np.ndarray
    train_indices: np.ndarray
    validation_indices: np.ndarray
    seed: int


def make_train_validation(seed, val_fraction=0.2, data_dir=DATA_DIR,
                           train_file=TRAIN_FILE):
    """Split KDDTrain+ only. This function never opens KDDTest+."""
    frame = read_raw(train_file, data_dir).reset_index(drop=True)
    labels = binary_labels(frame)
    indices = np.arange(len(frame))
    train_idx, val_idx = train_test_split(
        indices, test_size=val_fraction, stratify=labels, random_state=seed)
    train_idx, val_idx = np.sort(train_idx), np.sort(val_idx)
    if np.intersect1d(train_idx, val_idx).size:
        raise AssertionError("train and validation folds overlap")
    return TrainValidation(
        train=frame.iloc[train_idx].reset_index(drop=True),
        y_train=labels[train_idx],
        validation=frame.iloc[val_idx].reset_index(drop=True),
        y_validation=labels[val_idx],
        train_indices=train_idx,
        validation_indices=val_idx,
        seed=seed,
    )


class FieldEncoder:
    """Persistable NSL-KDD one-hot/scaling schema with original-field groups."""

    def __init__(self):
        self.preprocessor = None
        self.field_columns = {}
        self.column_names = []

    def fit(self, train_frame, y_train):
        features = train_frame.drop(columns=NON_FEATURE)
        self.preprocessor = NSLKDDPreprocessor().fit(
            features, y_train, scaler_fit="normal")
        cursor = 0
        self.field_columns = {}
        self.column_names = []
        for field in NUMERIC:
            self.field_columns[field] = [cursor]
            self.column_names.append(field)
            cursor += 1
        for field in CATEGORICAL:
            names = [f"{field}_{value}" for value in self.preprocessor.categories[field]]
            self.field_columns[field] = list(range(cursor, cursor + len(names)))
            self.column_names.extend(names)
            cursor += len(names)
        if cursor != self.preprocessor.n_features:
            raise ValueError("field groups do not match preprocessing feature schema")
        return self

    @property
    def n_features(self):
        return self.preprocessor.n_features

    def transform_all(self, frame):
        return self.preprocessor.transform(frame.drop(columns=NON_FEATURE, errors="ignore"))

    def transform_fields(self, frame, fields):
        selected = set(fields)
        indices = [index for field in FEATURE_FIELDS if field in selected
                   for index in self.field_columns[field]]
        if not indices:
            raise ValueError("field selection is empty")
        return self.transform_all(frame)[:, indices]

    def field_matrix(self, frame):
        """Return 41 columns for MI, with categorical values encoded as discrete IDs."""
        expanded = self.transform_all(frame)
        columns = []
        discrete = []
        for field in FEATURE_FIELDS:
            if field in CATEGORICAL:
                categories = self.preprocessor.categories[field]
                category_to_id = {value: index for index, value in enumerate(categories)}
                values = frame[field].astype(str).map(category_to_id).fillna(len(categories))
                columns.append(values.to_numpy(dtype=np.float64))
                discrete.append(True)
            else:
                columns.append(expanded[:, self.field_columns[field][0]])
                discrete.append(False)
        return np.column_stack(columns), np.asarray(discrete, dtype=bool)

    def rank_mutual_information(self, train_frame, y_train, seed):
        matrix, discrete = self.field_matrix(train_frame)
        scores = mutual_info_classif(matrix, y_train, discrete_features=discrete,
                                     random_state=seed)
        return {field: float(scores[index])
                for index, field in enumerate(FEATURE_FIELDS)}

    def rank_fields(self, scores):
        return sorted(FEATURE_FIELDS, key=lambda field: (-scores[field],
                                                         FEATURE_FIELDS.index(field)))

    def variance_correlation_control(self, train_frame):
        """Label-free field pruning on the full train fold's encoded features."""
        control_preprocessor = NSLKDDPreprocessor().fit(
            train_frame.drop(columns=NON_FEATURE), scaler_fit="train")
        matrix = control_preprocessor.transform(
            train_frame.drop(columns=NON_FEATURE)).astype(np.float64)
        variances = np.var(matrix, axis=0)
        groups = {
            field: [index for index in self.field_columns[field]
                    if variances[index] > 1e-12]
            for field in FEATURE_FIELDS
        }
        field_variance = {field: float(variances[groups[field]].sum())
                          for field in FEATURE_FIELDS}
        candidates = [field for field in FEATURE_FIELDS if groups[field]]
        priority = sorted(candidates, key=lambda field: (-field_variance[field],
                                                          FEATURE_FIELDS.index(field)))
        active_indices = sorted({index for indices in groups.values() for index in indices})
        correlation = np.zeros((matrix.shape[1], matrix.shape[1]), dtype=np.float64)
        active_matrix = matrix[:, active_indices]
        active_correlation = np.corrcoef(active_matrix, rowvar=False)
        correlation[np.ix_(active_indices, active_indices)] = active_correlation
        kept = []
        conflicts = []
        for field in priority:
            conflict = None
            for prior in kept:
                left, right = groups[field], groups[prior]
                cross = np.abs(correlation[np.ix_(left, right)])
                if cross.max(initial=0.0) > CORRELATION_THRESHOLD:
                    conflict = prior
                    break
            if conflict is None:
                kept.append(field)
            else:
                conflicts.append({"dropped": field, "kept": conflict,
                                  "threshold": CORRELATION_THRESHOLD})
        selected = [field for field in FEATURE_FIELDS if field in set(kept)]
        return selected, {"field_variance": field_variance,
                          "constant_fields": [field for field in FEATURE_FIELDS
                                              if not groups[field]],
                          "correlation_pruned": conflicts,
                          "correlation_threshold": CORRELATION_THRESHOLD}

    def fit_pca(self, train_frame, y_train, fields, retained_variance):
        if retained_variance not in PCA_VARIANCE_GRID:
            raise ValueError(f"unsupported PCA variance target: {retained_variance}")
        normal = np.asarray(y_train) == 0
        if not normal.any():
            raise ValueError("PCA requires normal train-fold rows")
        train_x = self.transform_fields(train_frame, fields)
        pca = PCA(n_components=retained_variance, svd_solver="full")
        pca.fit(train_x[normal])
        return pca

    def save_schema(self, path, selected_fields, variant, pca=None, selection=None):
        import json
        schema = {
            "variant": variant,
            "original_fields": FEATURE_FIELDS,
            "selected_fields": list(selected_fields),
            "field_columns": self.field_columns,
            "encoded_feature_names": self.column_names,
            "preprocessor_schema_hash": self.preprocessor.schema_hash,
            "preprocessor_n_features": self.preprocessor.n_features,
            "selection": selection,
            "model_n_features": (int(pca.n_components_) if pca is not None
                                 else sum(len(self.field_columns[f])
                                          for f in selected_fields)),
            "pca": None if pca is None else {
                "fit_on": "normal train-fold rows",
                "retained_variance_target": float(pca.n_components),
                "n_components": int(pca.n_components_),
                "explained_variance_ratio_sum": float(pca.explained_variance_ratio_.sum()),
            },
        }
        with open(path, "w") as stream:
            json.dump(schema, stream, indent=1)
        if pca is not None:
            np.savez(path.rsplit(".", 1)[0] + "_pca.npz", mean=pca.mean_,
                     components=pca.components_, explained_variance=pca.explained_variance_,
                     explained_variance_ratio=pca.explained_variance_ratio_)