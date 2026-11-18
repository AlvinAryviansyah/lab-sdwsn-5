# TLDQN Live Gym + Hybrid F2 Runbook

This experiment compares three modes for 100 sensors, seeds 4-6:

1. Same-build CSV TLDQN control, no IDS action.
2. Live-adaptive TLDQN through ns3-gym, no IDS action.
3. Live-adaptive TLDQN plus Hybrid F2: DTO-positive sensors are isolated, Bi-GAN contributes alarms, and Gym replans from live telemetry after isolation.

All three modes run the **same executable**, `ns3-sim/honeycomb-sdwsn.cc`. The route source is chosen at runtime:

| Dashboard mode | Simulator flags |
|---|---|
| 1 · Baseline · TLDQN dari CSV | `--routeSource=csv --idsSource=none --routeDir=...` |
| 2 · Adaptive live Gym | `--routeSource=gym --gymLiveAdaptive=true --openGymPort=5555 --idsSource=none` |
| 3 · Adaptive live Gym + isolasi sensor malicious (F2) | `--routeSource=gym --gymLiveAdaptive=true --openGymPort=5555 --idsSource=file --hybridPilotBigan=true --idsDir=...` |

`--routeSource=csv` is the default and keeps the original CSV behaviour. Gym mode needs the ns3-gym (`opengym`) module in the same ns-3 tree. Without that module the file still builds for CSV runs and rejects `--routeSource=gym` at startup.

For each seed, Run A is mode 2. Its telemetry produces the F2 decisions. Run B is mode 3 and must use the same seed, scenario, traffic, duration, and observation window as Run A. The parity gate checks the pre-action snapshot and applied route counters. The F2 run is paired against live-Gym Run A; mode 1 remains the CSV baseline in the dashboard.

## One-command run (recommended)

After the one-time preparation below (pull, copy the source into `scratch/`, copy the Bi-GAN checkpoint, install sklearn/pandas into `.venv-gym`), a single script runs all modes for seeds 4-6:

```sh
cd "$HOME/experiments/sdwsn-tldqn"
bash ns3-sim/tldqn_gym/run_three_modes.sh            # seeds 4 5 6
SEEDS="5" bash ns3-sim/tldqn_gym/run_three_modes.sh  # one seed only
DRY_RUN=1 bash ns3-sim/tldqn_gym/run_three_modes.sh  # print commands only
```

The script first checks the prerequisites: matching scratch source, no stale scratch copies, NumPy aliases, Python dependencies, and the checkpoint hash. It then moves existing run folders for the selected seeds to `ns3-sim/tldqn_gym/runs_archive/<time>/`. Nothing is deleted. Per seed it runs Mode 1, Mode 2 with the agent in the background, the parity check, the F2 decisions, Mode 3, and the parity check again. It ends by building the dashboard and stops at the first failure. Agent and simulator logs are written to `agent.log` and `simulator.log`, and parity results to `parity.json`, inside each run folder.

The manual steps below do the same thing one command at a time.

## Prepare

Use the isolated ns-3.48 tree and `.venv-gym` described in `ns3-sim/tldqn_gym/README.md`. Do not use the shared `/app/ns-3-dev` tree. Pull the branch, copy the single simulator source, and rebuild it:

```sh
PROJECT="$HOME/experiments/sdwsn-tldqn"
NS3="$PROJECT/ns3-src/ns-3.48"
RUNS="$PROJECT/ns3-sim/tldqn_gym/runs"
SCENARIOS="$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/scenarios"
ROUTES="$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/routes"
cd "$PROJECT"
git pull --ff-only origin feat/ai-ns3-integration
cp ns3-sim/honeycomb-sdwsn.cc "$NS3/scratch/honeycomb-sdwsn.cc"
# The old separate Gym copy is gone; remove it if an earlier checkout left it in scratch.
rm -rf "$NS3/scratch/tldqn_gym"
cd "$NS3"
./ns3 configure --disable-examples
./ns3 build honeycomb-sdwsn -j 2
```

Run one seed at a time so the Gym bridge port is not shared by concurrent runs. The examples below use seed 4; repeat with seeds 5 and 6 and fresh directories.

## Mode 1: CSV Baseline

`CSV_RUN` must not exist before starting; the simulator creates it.

```sh
SEED=4
CSV_RUN="$RUNS/csv_control_adaptive_ns348_100_s$SEED"
cd "$NS3"
./ns3 run "honeycomb-sdwsn --numNodes=100 --seed=$SEED --simTime=14 --telemWindow=7.3 \
  --numUsers=10 --numPackets=50 --profile=paper --wifiStd=ac --maxRange=150 \
  --wdTimeout=0.1 --wdLate=1 --aiDir=$SCENARIOS --routeDir=$ROUTES \
  --routeSource=csv --idsSource=none --outputDir=$CSV_RUN --telemDir=$CSV_RUN/telemetry"
```

## Mode 2: Live Gym Run A

The Run A root holds the agent audit. Its nested `ns3` directory must not exist before the simulator starts.

Terminal 1:

```sh
ADAPTIVE_RUN="$RUNS/tldqn_live_adaptive_100_s$SEED"
mkdir -p "$ADAPTIVE_RUN"
cd "$PROJECT"
.venv-gym/bin/python ns3-sim/tldqn_gym/agent.py --port 5555 --nodes 100 --seed "$SEED" \
  --expect-reroute --live-adaptive --audit "$ADAPTIVE_RUN/audit.json"
```

Terminal 2:

```sh
cd "$NS3"
./ns3 run "honeycomb-sdwsn --numNodes=100 --seed=$SEED --simTime=14 --telemWindow=7.3 \
  --numUsers=10 --numPackets=50 --profile=paper --wifiStd=ac --maxRange=150 \
  --wdTimeout=0.1 --wdLate=1 --routeSource=gym --openGymPort=5555 --gymLiveAdaptive=true \
  --aiDir=$SCENARIOS --idsSource=none --outputDir=$ADAPTIVE_RUN/ns3"
```

## Generate F2 Decisions

The threshold is frozen at `0.4741064757` (selected on labeled validation seeds 1-3 for Bi-GAN run `pilot_20261107_211217`). Do not tune it on seeds 4-6.

The Bi-GAN checkpoint is not in git (`ml/checkpoints/` is ignored). Copy it to the server once, then check `model.pt` there with `sha256sum` (expected `1cb24041e96aec2bf5d494b087080ce4cc689fca0c80c730c09ea077a28084f7`):

```sh
# on the laptop
scp -r ml/checkpoints/bigan_ns3_pilot/pilot_20261107_211217 \
  lab@<server>:~/experiments/sdwsn-tldqn/ml/checkpoints/bigan_ns3_pilot/
```

`.venv-gym` also needs `scikit-learn` and `pandas` for this step. Install them with NumPy pinned, so the ns3-gym NumPy aliases survive: `.venv-gym/bin/python -m pip install scikit-learn pandas "numpy==<current version>"`. `HYBRID_RUN` may exist for its audit and decision subfolders, but `HYBRID_RUN/ns3` must not exist before the simulator starts.

```sh
HYBRID_RUN="$RUNS/tldqn_live_hybrid_f2_100_s$SEED"
mkdir -p "$HYBRID_RUN"
cd "$PROJECT"
.venv-gym/bin/python ml/bigan_ns3_pilot.py predict --run-id pilot_20261107_211217 \
  --telem-dir "$ADAPTIVE_RUN/ns3/telemetry" --nodes 100 --seed "$SEED" \
  --threshold 0.4741064757 --out-dir "$HYBRID_RUN/predictions"

.venv-gym/bin/python ml/hybrid_ids.py \
  --telem-dir "$ADAPTIVE_RUN/ns3/telemetry" --scenario-dir "$SCENARIOS" \
  --bigan-pred-dir "$HYBRID_RUN/predictions" --route-dir "$ROUTES" \
  --out-dir "$HYBRID_RUN/decisions" --nodes 100 --seeds "$SEED" --fusion F2
```

The decision directory must be new. F2 uses telemetry window 0 (`[0, 7.3 s)`) and requires `T_obs + wdLate <= T_ids` (`7.3 + 1.0 <= 8.3`).

## Mode 3: Live Gym Run B + F2

Terminal 1:

```sh
cd "$PROJECT"
.venv-gym/bin/python ns3-sim/tldqn_gym/agent.py --port 5555 --nodes 100 --seed "$SEED" \
  --expect-reroute --live-adaptive --audit "$HYBRID_RUN/audit.json"
```

Terminal 2:

```sh
cd "$NS3"
./ns3 run "honeycomb-sdwsn --numNodes=100 --seed=$SEED --simTime=14 --telemWindow=7.3 \
  --numUsers=10 --numPackets=50 --profile=paper --wifiStd=ac --maxRange=150 \
  --wdTimeout=0.1 --wdLate=1 --routeSource=gym --openGymPort=5555 --gymLiveAdaptive=true \
  --aiDir=$SCENARIOS --idsSource=file --idsDir=$HYBRID_RUN/decisions \
  --hybridPilotBigan=true --outputDir=$HYBRID_RUN/ns3"
```

The F2 decision is applied at t=8.3 s before the second Gym request. If no alternate route exists, the failed route must be reported; no route is invented.

## Validate and Build Dashboard

Run this for each seed after its Run B completes:

```sh
cd "$PROJECT"
PYTHONDONTWRITEBYTECODE=1 .venv-gym/bin/python ns3-sim/tldqn_gym/check_parity.py \
  --audit "$HYBRID_RUN/audit.json" --gym-dir "$HYBRID_RUN/ns3" \
  --control-dir "$ADAPTIVE_RUN/ns3" --mode adaptive_hybrid
```

The gate checks initial routes against the frozen baseline, Run A/B pre-action telemetry and snapshot, F2 isolation IDs, live measurements, route changes, unresolved routes, and simulator IDS counters. After seeds 4-6 pass, build the root Research Console:

```sh
cd "$PROJECT"
.venv-gym/bin/python ml/build_dashboard.py
```

The dashboard's **Mode eksperimen** dropdown and **Mode comparison** tab list the three modes: Baseline (CSV), Adaptive live Gym, and Adaptive live Gym + sensor isolation (F2). A mode with no collected run stays in the dropdown but is disabled and marked "belum dijalankan". Until a validated F2 artifact is present for a seed, that row is shown as pending. The F2 delta is paired against its same-seed live-Gym Run A.

Keep the ns3-gym bridge on the isolated experiment host/network and restrict its listening port as described in the server prerequisites above.
