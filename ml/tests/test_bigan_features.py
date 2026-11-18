import os
import sys
import tempfile
import unittest
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import synth
from bigan_features import FEATURE_FIELDS, FieldEncoder, make_train_validation
from nslkdd_data import COLUMNS


class TestTrainValidationIsolation(unittest.TestCase):
    def test_split_does_not_require_or_read_test_file(self):
        with tempfile.TemporaryDirectory() as directory:
            frame, _ = synth.make_df(500, seed=10, attack_fraction=0.3)
            frame = frame[COLUMNS]
            frame.to_csv(os.path.join(directory, "KDDTrain+.txt"), index=False, header=False)
            split = make_train_validation(seed=7, data_dir=directory)
            self.assertEqual(len(split.train) + len(split.validation), len(frame))
            self.assertFalse(np.intersect1d(split.train_indices,
                                            split.validation_indices).size)
            self.assertAlmostEqual(split.y_train.mean(), split.y_validation.mean(), delta=0.02)


class TestFieldEncoder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train, cls.y = synth.make_df(900, seed=2, attack_fraction=0.3)
        cls.encoder = FieldEncoder().fit(cls.train, cls.y)

    def test_preserves_41_original_fields_and_grouped_one_hot_columns(self):
        self.assertEqual(len(FEATURE_FIELDS), 41)
        self.assertEqual(len(self.encoder.field_columns), 41)
        selected = ["protocol_type", "service", "src_bytes"]
        X = self.encoder.transform_fields(self.train, selected)
        expected = sum(len(self.encoder.field_columns[field]) for field in selected)
        self.assertEqual(X.shape, (len(self.train), expected))
        self.assertGreater(len(self.encoder.field_columns["service"]), 1)

    def test_mutual_information_ranks_whole_fields_deterministically(self):
        scores = self.encoder.rank_mutual_information(self.train, self.y, seed=3)
        self.assertEqual(set(scores), set(FEATURE_FIELDS))
        first = self.encoder.rank_fields(scores)
        self.assertEqual(first, self.encoder.rank_fields(scores))

    def test_variance_correlation_control_is_label_free(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            selected_a, info_a = self.encoder.variance_correlation_control(self.train)
            selected_b, info_b = self.encoder.variance_correlation_control(self.train)
        self.assertEqual(selected_a, selected_b)
        self.assertEqual(info_a, info_b)
        self.assertTrue(set(selected_a).issubset(FEATURE_FIELDS))
        self.assertFalse(caught)

    def test_pca_is_fit_on_normal_train_rows_only(self):
        fields = FEATURE_FIELDS[:8]
        X = self.encoder.transform_fields(self.train, fields)
        pca = self.encoder.fit_pca(self.train, self.y, fields, 0.95)
        expected = X[self.y == 0].mean(axis=0)
        np.testing.assert_allclose(pca.mean_, expected, atol=1e-5)
        self.assertLessEqual(pca.n_components_, X.shape[1])

    def test_unknown_categories_keep_the_train_schema(self):
        changed = self.train.copy()
        changed["service"] = "unseen_service"
        transformed = self.encoder.transform_all(changed)
        self.assertEqual(transformed.shape[1], self.encoder.n_features)
        service_cols = self.encoder.field_columns["service"]
        raw = self.encoder.preprocessor._raw_matrix(changed.drop(columns=["label", "difficulty"]))
        np.testing.assert_array_equal(raw[:, service_cols], 0.0)
        expected = -self.encoder.preprocessor.mean[service_cols] / self.encoder.preprocessor.scale[service_cols]
        np.testing.assert_allclose(transformed[:, service_cols],
                       np.broadcast_to(expected, transformed[:, service_cols].shape),
                       atol=1e-6)


if __name__ == "__main__":
    unittest.main()