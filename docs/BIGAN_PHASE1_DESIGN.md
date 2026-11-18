# Bi-GAN Phase 1: Feature Selection and Extraction

## Scope and preservation

This phase is an offline NSL-KDD experiment on the refactored Bi-GAN implementation.
It does not modify `ai_models.pt`, the Step 1-4 pipeline, existing checkpoints or
results, or any NS-3 source. NS-3 integration is a separate Phase 2 and is not part
of this design.

The paper's SDWSNIDS dataset in `data/SDWSNIDS_Dataset/` contains the released
simulation source and a video link, not usable packet or flow traffic records. NSL-KDD
therefore remains the available offline benchmark; this is a documented research
assumption, not a claim that it reproduces the paper's traffic features.

## Data protocol

- Seeds 1-5 define paired stratified 80/20 train/validation splits from KDDTrain+ and
  the model/training random seed. Each variant and architecture uses the same split
  for a given seed.
- Preprocessing schemas and numeric scaling are fit only on the train fold; numeric
  scaling statistics use normal train-fold rows, matching the refactored Bi-GAN.
- The experiment/training command reads KDDTrain+ only. It must not open KDDTest+.
- KDDTest+ is opened only by the explicit final-evaluation command, after all feature
  and PCA choices have been fixed using validation.
- No score direction is flipped. A validation direction check passes when validation
  ROC AUC for the prescribed anomaly score `-logit D(x, E(x))` is greater than 0.5.
  This is a direction diagnostic, not a minimum-performance or experiment-success
  threshold. Failed checks remain in the report and are evaluated as-is on test.

## Variants

- `B0`: all original fields, expanded with the train-fitted one-hot schema (normally
  122 model inputs).
- `B1`: supervised mutual-information ranking over the 41 original fields. Numeric
  fields are continuous; categorical fields are discrete. All one-hot columns from a
  selected categorical field are retained together. Candidate field counts are
  5, 10, 15, 20, 30 and 41. Select the count with the highest validation ROC AUC;
  exact ties prefer fewer fields.
- `B2`: B1's validation-selected fields followed by PCA. PCA is fit only on normal
  rows of the train fold. Candidate retained-variance levels are 90%, 95% and 99%;
  select the level with the highest validation ROC AUC, with exact ties preferring
  fewer components. PCA is an explicit research assumption; the paper does not
  specify a feature-extraction algorithm.
- `V+C control`: a label-free control. Remove constant expanded columns/fields and
  greedily prune whole fields when any pair of their expanded columns has absolute
  Pearson correlation above 0.95. Prefer the field with larger summed train-fold
  variance; exact ties keep the earlier original field. This control uses the full
  train fold and a scaler fit on the full fold (not the normal-only scaler), but never
  labels, validation, or test data.

All four variants run for seeds 1-5 with `n_hidden` 1 and 2, using the same Bi-GAN
training configuration otherwise. Candidate B1/B2 validation search models are
logged; only the selected pipeline for each variant is included in final test
evaluation. The full grid has 110 candidate trainings (including B0 and V+C); using
the existing checkpoint measurements of roughly 9-13 s per 20-epoch model gives an
initial training-only budget estimate of 16.5-23.8 minutes. This excludes feature
search, validation inference, checkpoint I/O and final test evaluation; actual times
are measured and reported by the run.

## Evaluation and reporting criteria

There is no minimum AUC, accuracy, F1, or recall required for a result to count as a
successful experiment. Readiness is procedural: all planned seed/architecture/variant
runs are either completed or explicitly recorded as failed; preprocessing and model
choices are derived without test data; the prescribed score direction and any failure
are reported; and reports include every seed, selected feature/component counts,
validation and final test metrics, parameter/model size, training and inference time.

For every selected model report validation/test ROC AUC, confusion counts, accuracy,
precision, recall/TPR, FPR and F1 at a threshold selected on validation using the
refactored weighted-F1 policy at 10% prevalence. Also report prevalence-adjusted
precision/F1 at 10%, and per-attack-type test recall (including attack types absent
from the train fold). Summaries include mean and sample standard deviation over the
five seeds, alongside the per-seed records. Model selection ranks candidates by raw
validation ROC AUC regardless of the direction diagnostic; ties use the smaller
representation. Test metrics never affect selection.

Record training/search wall time, selected-model training time, model parameter
count, checkpoint bytes, model-only inference latency per record, and transform-plus-
inference latency per record. These are measurements, not pass/fail gates.

## Output layout

- Checkpoints and schemas: `ml/checkpoints/bigan_fs/<run-id>/`
- Search and validation records: `ml/reports/bigan_fs/<run-id>/`
- Final test report: `ml/reports/bigan_fs/<run-id>/final_test.json`

The run ID must be new; commands refuse to overwrite an existing run. Training and
final test evaluation are separate commands so the test set cannot enter model
selection.

## Reproduction commands

```bash
# Phase 1 training + validation search; reads KDDTrain+ only
.venv/bin/python ml/run_bigan_fs.py train --run-id phase1_2026-11-08

# Run once after reviewing the completed validation report
.venv/bin/python ml/run_bigan_fs.py evaluate-test --run-id phase1_2026-11-08
```

The first command writes `training.json` and `validation_search.json`; the second
writes `final_test.json` and `final_test.md`. The training report records the SHA-256
of KDDTrain+; the final report records KDDTest+'s SHA-256. A finished report or run ID
is never silently overwritten.