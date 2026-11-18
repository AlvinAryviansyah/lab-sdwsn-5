# Bi-GAN NS-3 Integration Pilot

## Scope

This is a small, alarm-only integration using the existing `idsSource=bigan` mode.
It does not load or deploy any B0/B1/B2/V+C Phase 1 checkpoint. It trains a fresh
one-hidden-layer Bi-GAN on benign NS-3 telemetry, calibrates the threshold from a
separate benign seed, and evaluates predictions against mixed benign/attack seeds.
The model never reads `actual_mal`; ground truth is used only to configure the
simulated attack and by the offline evaluator.

`idsSource=bigan` consumes only
`bigan_pilot_predictions_<n>_s<seed>.csv` (`node_id,score,threshold,pred_intrusion`).
It reports alarms and confusion metrics at T_ids. It never sets `g_blocked`, applies
DTO decisions, or changes routes. Existing `cpp`, `file`, and `none` behavior remains
unchanged. The existing prevention stage sends a delegator notification only if at
least one pilot alarm exists.

## Feature schema

One example is one sensor in telemetry window 0 (`[0, 7.3 s)`). The 32 inputs are
derived from the existing NS-3 packet/radio traces and passive observer telemetry:

- IP-originated packet count/bytes, mean originated packet bytes, IP received/local
  delivery counts.
- MAC ACK/NACK, retry/other drops, and response timeouts.
- PHY transmitted MPDU/bytes, mean transmitted MPDU bytes, received-good/failed and
  dropped MPDU counts.
- Watchdog observer count, observed watch counts by forwarding outcome, and neighbor
  observed packet/MAC counters, mean RSSI/SNR, and forwarding delay.

Count/byte features use `log1p`, then a `StandardScaler` fit on benign training runs.
Only `self_ip_orig_*`, local receive counts, and radio transmit/receive trace counters
are used from `self_*`; self-forward/drop counters and `self_energy_j` are excluded.
Peer-observed watchdog/link features are included. `node_id` and `window` identify the
record but are not model inputs. The CSV feature rows contain no labels.

The current telemetry files do **not** export per-packet SrcIP/DstIP, transport
ports, packet-type/response/connection fields, or per-node UDP/TCP-separated flow
statistics. The C++ trace callback internally sees IPv4 source/destination/protocol,
but currently persists only aggregates; transport ports are not parsed or saved.
Accordingly this pilot uses the packet/radio aggregates that are actually persisted,
not invented replacements for the paper's unavailable fields. It is a useful
behavioral pilot, not a feature-identical reproduction of the paper's flow/packet IDS.

Example feature CSV shape (values below are an existing trace extraction smoke row,
not a benign-training sample or a Phase 2 result):

```csv
node_id,window,origin_packets,origin_bytes,mean_origin_packet_bytes,phy_tx_mpdu,observed_rx_ok_mpdu,observed_forwarded
0,0,50,33400,668,193,1458,66
```

Prediction CSV shape (label-free; values are illustrative only):

```csv
node_id,score,threshold,pred_intrusion
0,0.12,0.35,0
```

## Data protocol

- `prepare-inputs` creates separate all-normal scenario inputs for clean training and
  held-out calibration seeds, plus evaluation scenarios copied from existing attack
  ground truth. Routes use `--trust-source=none`; TLDQN itself is unchanged.
- Clean NS-3 runs use `idsSource=none`, `simTime=10`, and `telemWindow=7.3`. This
  avoids the 15.3 s delegator event; the first telemetry window is complete by the
  8.3 s IDS decision point (`wdLate=1 s`).
- The trainer reads only telemetry CSVs for the clean training seeds. It uses the
  refactored G/E/D training loop with `n_hidden=1`, no feature selection/PCA, and no
  hyperparameter search.
- Threshold = 95th percentile of scores from the held-out benign calibration seed
  (nominal 5% clean calibration FPR). This is a pilot policy assumption; no attack
  labels are used for direction, threshold, or model selection, and the score is
  never flipped.
- `predict` reads only telemetry and writes a prediction-only CSV. `evaluate` joins
  ground truth afterward for precision, recall, F1, FPR, AUC, and confusion counts.
- For NS-3 alarm replay, run B uses the same scenario and `idsSource=bigan`. The
  prediction-only file is loaded separately from the scenario file that controls
  simulated attacker behavior. `verify-replay` must show identical feature vectors
  for run A and B before interpreting results.

## Pilot commands

Run from the repository root after copying the source and `ns3-sim/results/bigan_pilot`
inputs to the ns-3.48 build root (`NS3_DIR`, e.g. `/app/ns-3-dev`). The training and
prediction commands can run on the laptop if the telemetry files are copied back.
The scenario and route inputs for nodes=100, clean seeds 101-104, and evaluation seeds
1-3 have already been prepared in `ns3-sim/results/bigan_pilot/`. `prepare-inputs`
refuses to overwrite that directory; use a new `--out-dir` when regenerating it.
Set `LAB_ROOT` to the repository path and `NS3_DIR` to the ns-3.48 build root before
using the commands below.

```bash
# Inputs clean/eval untuk seed 101-104 dan 1-3 sudah ada di folder default.
# Untuk membuat set baru, pilih --out-dir yang belum ada:
.venv/bin/python ml/bigan_ns3_pilot.py prepare-inputs \
  --nodes 100 --clean-seeds 101 102 103 --calibration-seed 104 --eval-seeds 1 2 3 \
  --out-dir ns3-sim/results/bigan_pilot_run2

# Copy ns3-sim/honeycomb-sdwsn.cc and ns3-sim/results/bigan_pilot/ to $NS3_DIR,
# then build once in the ns-3.48 root.
cd "$NS3_DIR"
./ns3 build honeycomb-sdwsn

# Run clean training/calibration scenarios, all with attack-free ground truth.
for seed in 101 102 103 104; do
  ./ns3 run "honeycomb-sdwsn --numNodes=100 --simTime=10 --seed=$seed \
    --aiDir=results/bigan_pilot/scenarios --routeDir=results/bigan_pilot/routes \
    --idsSource=none --telemDir=results/bigan_pilot/telemetry_clean \
    --telemWindow=7.3 --outputDir=results/bigan_pilot/runs/clean_${seed} \
    --outCsv=results/bigan_pilot/runs/clean_${seed}/metrics.csv"
done

# Train on 3 clean seeds; hold out seed 104 for benign threshold calibration.
cd "$LAB_ROOT"
.venv/bin/python ml/bigan_ns3_pilot.py train --run-id pilot100 \
  --telem-dir "$NS3_DIR/results/bigan_pilot/telemetry_clean" --nodes 100 \
  --train-seeds 101 102 103 --calibration-seed 104

# Run A: attack scenarios, no IDS action. Repeat for seeds 1, 2, 3.
# Use outCsv/telemDir paths tagged with _A.
cd "$NS3_DIR"
./ns3 run "honeycomb-sdwsn --numNodes=100 --simTime=10 --seed=1 \
  --aiDir=results/bigan_pilot/scenarios --routeDir=results/bigan_pilot/routes \
  --idsSource=none --telemDir=results/bigan_pilot/telemetry_A \
  --telemWindow=7.3 --outputDir=results/bigan_pilot/runs/eval_A_1 \
  --outCsv=results/bigan_pilot/runs/eval_A_1/metrics.csv"

# Predict from run A telemetry; predictions are label-free.
cd "$LAB_ROOT"
.venv/bin/python ml/bigan_ns3_pilot.py predict --run-id pilot100 \
  --telem-dir "$NS3_DIR/results/bigan_pilot/telemetry_A" --nodes 100 --seed 1 \
  --out-dir "$NS3_DIR/results/bigan_pilot/predictions"

# Evaluate labels only after prediction, then replay with alarms and no isolation.
.venv/bin/python ml/bigan_ns3_pilot.py evaluate --run-id pilot100 \
  --pred-dir "$NS3_DIR/results/bigan_pilot/predictions" \
  --scenario-dir "$NS3_DIR/results/bigan_pilot/scenarios" --nodes 100 --seeds 1 \
  --out ml/reports/bigan_ns3_pilot/pilot100/eval.json
cd "$NS3_DIR"
./ns3 run "honeycomb-sdwsn --numNodes=100 --simTime=10 --seed=1 \
  --aiDir=results/bigan_pilot/scenarios --routeDir=results/bigan_pilot/routes \
  --idsSource=bigan --biganDir=results/bigan_pilot/predictions \
  --telemDir=results/bigan_pilot/telemetry_B --telemWindow=7.3 \
  --outputDir=results/bigan_pilot/runs/eval_B_1 \
  --outCsv=results/bigan_pilot/runs/eval_B_1/metrics.csv"
```

Repeat the two NS-3 commands, prediction, evaluation, and replay check for seeds 2
and 3. Check A/B features before trusting the pilot:

```bash
.venv/bin/python ml/bigan_ns3_pilot.py verify-replay \
  --telem-a "$NS3_DIR/results/bigan_pilot/telemetry_A" \
  --telem-b "$NS3_DIR/results/bigan_pilot/telemetry_B" --nodes 100 --seed 1
```

Expected B-run invariants: `ids_source_bigan_alarm_only=1`,
`nodes_blocked=0`, `isolation_transit_drops=0`, and `reroute_changed=0`. Alarm
count must match the pure prediction CSV. This is a pilot only; do not run a full
node/seed sweep until clean-run training, A/B replay, and alarm application are
verified on the ns-3 host.

## Held-out threshold experiment

For the 100-node follow-up, the existing model is unchanged. Attack seeds 1-3 are
exploratory validation data: their labels select threshold `0.4741064757` by
maximizing pooled F1 under pooled FPR <= 0.05. This is a label-informed selection,
not the original benign-only calibration. The frozen selection, seed split, and
model and validation-input hashes are in
`ml/reports/bigan_ns3_pilot/pilot_20261107_211217/threshold_selection.json`.

`ns3-sim/results/bigan_pilot_test_4_6/` contains separate test inputs for seeds
4-6. Seeds 4 and 5 use the archived scenarios; seed 6 selects 10 malicious nodes
using the same `default_rng(seed * 100000 + nodes)` policy. All routes use the
same TLDQN checkpoint and label-free trust as the pilot. Do not select or adjust
the threshold using these test labels or results. The frozen selection file's
`test_status` records the state before test execution.

Test telemetry for seeds 4-6 was collected on the ns-3.48 host and evaluated
offline with the frozen threshold: pooled TP=27, TN=263, FP=7, FN=3,
precision=0.794, recall=0.900, F1=0.844, and FPR=0.026. These results are from
three 100-node grayhole/flooding scenarios. Their ns-3 alarm replay produced
identical window-0 features and the same confusion matrices, with 11, 12, and
11 alarms respectively. No nodes were blocked and no routes were changed.

After collecting test telemetry, use `predict --threshold 0.4741064757` for
each seed. Omitting `--threshold` preserves the original checkpoint calibration;
the override does not modify the checkpoint. Supply `evaluate --selection-seeds
1 2 3` to record which labels informed threshold selection; when omitted, the
evaluator reports selection provenance as unknown.

## DTO and telemetry Bi-GAN hybrid pilot

This follow-up combines the frozen DTO detector with the telemetry Bi-GAN
predictions for the same run A and window `[0, 7.3 s)`. F2 remains the main
policy: DTO `malicious` triggers isolation and TLDQN reroute; Bi-GAN contributes
an alarm only. `insufficient_evidence` never triggers DTO isolation. Ground
truth is not an input to either decision. The Bi-GAN threshold was selected
using attack labels on validation seeds 1-3; seeds 4-6 are held-out tests.

The saved node and link telemetry for run A must be accompanied by the original
`telemetry_meta_*` and `ids_snapshot_*` files from the same ns-3 run. The
prediction metadata JSON is also required: the hybrid exporter checks that its
node and link hashes match run A, and checks the recorded observation timing.
The TLDQN checkpoint and table hashes are verified before rerouting. The pilot
exporter refuses to overwrite an existing output directory.

After those inputs are available, from the repository root:

```bash
.venv/bin/python ml/hybrid_ids.py \
  --telem-dir ns3-sim/results/bigan_test_4_6_20261107_214507 \
  --scenario-dir ns3-sim/results/bigan_pilot_test_4_6/scenarios \
  --route-dir ns3-sim/results/bigan_pilot_test_4_6/routes \
  --bigan-pred-dir ml/reports/bigan_ns3_pilot/pilot_20261107_211217/predictions_test_4_6 \
  --out-dir ns3-sim/results/bigan_hybrid_f2_decisions_4_6 \
  --nodes 100 --seeds 4 5 6 --fusion F2
```

Run B uses `--idsSource=file --idsDir=<decision-dir> --hybridPilotBigan=true`
with the same scenario, routes, seed, duration, and telemetry settings as run A.
The opt-in flag evaluates Bi-GAN from the hybrid decisions after simulation and
suppresses the unrelated legacy NSL-KDD monitoring windows. Existing defaults and
the original alarm-only mode are unchanged. Verify the run A/B pre-action
snapshots, DTO inputs and Bi-GAN feature vectors, then compare applied alarms,
isolation, rerouting and confusion counts against the exported decisions.

Run B was executed on the ns-3.48 host for 100 nodes and seeds 4-6. All three
pre-action snapshots and DTO input windows matched run A, all three Bi-GAN
feature vectors matched, and applied alarms, isolation and reroute counts
matched the exported decisions. DTO isolated 14 nodes: 12 malicious and 2
normal (pooled precision 0.857, recall 0.400, F1 0.545, FPR 0.0074). Bi-GAN
contributed 34 alarms (TP=27, FP=7, FN=3, TN=263); F2 did not isolate on
Bi-GAN alarms alone. Across the three paired runs, mean benign PDR increased
2.12 percentage points, benign packets received increased by 219, and benign
packets sent decreased by 17. These are small, 10-second simulations, not a
general performance guarantee. The 15.3-second delegator event does not execute,
so these runs cannot assess it.

The recorded gate and evaluation reports are in
`ml/reports/bigan_ns3_pilot/pilot_20261107_211217/hybrid_f2_4_6/`.
The dashboard's optional `Hybrid F2 · NS-3 telemetry Bi-GAN` configuration is
shown only when the matching decisions and replay files are available under
`ns3-sim/results/bigan_hybrid_f2_decisions_4_6/` and
`ns3-sim/results/bigan_hybrid_f2_4_6/`. It validates source hashes and metrics,
and reports whether the pre-action A/B gate passed.

### Bi-GAN-Only Isolation Extension

`--fusion BIGAN` is an opt-in project experiment: only the telemetry Bi-GAN
prediction drives isolation and rerouting; DTO remains available for diagnostics.
It is not the paper's stated fusion rule, and F2 remains the paper-aligned main
policy. The threshold used below was selected using validation labels from seeds
1-3; seeds 4-6 are held-out for this evaluation.

The decisions and reroute tables have been generated at
`ns3-sim/results/bigan_hybrid_biganonly_decisions_4_6/`. On the held-out seeds,
Bi-GAN isolated 34 nodes: 27 malicious and 7 benign (precision 0.794, recall
0.900, F1 0.844, FPR 0.026). Rerouting changed 40 table entries total, with no
failed paths. These are decision-level results; network impact still requires
the ns-3 run B below.

Copy the decisions, scenario inputs, route tables, and updated C++ source to the
ns-3.48 host. Then run the same scenario and duration as run A for each seed:

```bash
mkdir -p results/bigan_hybrid_biganonly_4_6
for seed in 4 5 6; do
  ./ns3 run "honeycomb-sdwsn --numNodes=100 --simTime=10 --seed=$seed \
    --aiDir=results/bigan_pilot_test_4_6/scenarios \
    --routeDir=results/bigan_pilot_test_4_6/routes \
    --idsSource=file \
    --idsDir=results/bigan_hybrid_biganonly_decisions_4_6 \
    --hybridPilotBigan=true --telemWindow=7.3 \
    --telemDir=results/bigan_hybrid_biganonly_4_6/telemetry \
    --outputDir=results/bigan_hybrid_biganonly_4_6 \
    --outCsv=results/bigan_hybrid_biganonly_4_6/metrics_100_s${seed}.csv" \
    > "results/bigan_hybrid_biganonly_4_6/log_100_s${seed}.txt" 2>&1
done
```

Compare decisions and applied C++ metrics against run A using
`ml/hybrid_eval.py evaluate`, then verify application with `ml/hybrid_eval.py
applied`. Run A/B must retain identical scenario, routes, seed, duration, and
telemetry window. Do not interpret the decision-level scores as a network
performance gain until this replay passes.

## Local checks and current execution limit

`ml/tests/test_bigan_ns3_pilot.py` uses synthetic telemetry to exercise the feature,
train, predict, evaluator, and alarm-file contracts. On the ns-3.48 host, benign
seeds 101-104 were collected for training and calibration, and attack seeds 1-3
were collected and replayed. Their replay features matched, and alarm counts and
confusion matrices agreed with offline predictions. Those attack seeds are now
validation data for the threshold experiment above, not independent final tests.
This workspace has no ns-3.48 runtime; test seeds 4-6 were run on the host.