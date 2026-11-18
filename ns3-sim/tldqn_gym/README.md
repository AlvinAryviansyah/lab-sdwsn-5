# TLDQN through ns3-gym (isolated prototype)

This folder holds the Python side of the ns3-gym bridge (agent, frozen policy, protocol, parity checker). There is **one simulator**, `ns3-sim/honeycomb-sdwsn.cc`. `--routeSource=csv` (the default) reads the TLDQN next-hop CSV as before. `--routeSource=gym` bootstraps routes through the Python TLDQN policy over ns3-gym, and with `--gymLiveAdaptive=true` replans once from live NS-3 telemetry at the IDS checkpoint. The Gym path does not change CSV-mode behaviour, baseline artifacts, or checkpoints. See [the three-mode runbook](../../docs/TLDQN_GYM_HYBRID_F2_RUNBOOK.md) for the dashboard modes.

## What is and is not live

- The TLDQN checkpoint is frozen and hash-checked. No training occurs.
- At simulation time 1.3 s, immediately before sensor flows are scheduled, the simulator requests one batched bootstrap route action. In live-adaptive TLDQN-only mode, it requests a second batch at t=8.3 s and uses current MAC link outcomes, watchdog trust and remaining energy to replan routes for continuing flows. This is one batch checkpoint, not a Gym round trip per packet.
- The Python agent logs each request phase and one selected next-hop per source flow before sending the action. For live-adaptive TLDQN-only runs, use `--idsSource=none`, `--gymLiveAdaptive=true`, `--expect-reroute`, and `--live-adaptive`. DTO/Bi-GAN actions are not applied.
- The initial route uses the baseline Python proxy because no traffic telemetry exists yet. The checkpoint reroute consumes live telemetry; unmeasured links fall back to proxy estimates. The frozen model has not been retrained on this mixed feature source, so this is an exploratory adaptive mode, not a deployment claim.
- Live-adaptive Gym reads only the `actual_mal` scenario label to configure simulated attackers; it does not load Bi-GAN prediction windows or DTO decisions. The paired legacy CSV control still needs its window CSV. No TLDQN route CSV is read at Gym simulator runtime.
- Labels are not sent in Gym observations. Scenario ground truth stays local to the simulator for attacker behavior and evaluation.
- Gym reward is a zero-valued protocol placeholder, not a measured objective. Inference wall time is reported separately from simulated time.
- The recorded baseline covers 100 nodes and seeds 4, 5, and 6 only.

## Local checks

From the project root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s ns3-sim/tldqn_gym -p 'test_*.py' -v
```

These tests verify in-memory policy parity, protocol validation, an isolated C++ route-receiver harness, and a syntax-only check using a local declaration stub. They do **not** prove that upstream ns3-gym builds or runs with ns-3.48.

## Isolated server prerequisites

Use a new Linux experiment directory with no path spaces. Do not copy this source into an existing ns-3 tree or use its current results/build directories. Use a fresh ns-3.48 source tree, a fresh Python virtual environment, and separate build and output directories. Keep the project's original `.venv` untouched.

Upstream ns3-gym was inspected at branch `app-ns-3.36+`, commit `cfff7f3217b7da2c263c717a4540d6adf189eeb1`. Its example documents ns-3.40, not ns-3.48; compatibility remains unverified. Its Python API also uses legacy Gym's four-value `step()` result and removed NumPy aliases (`np.int`, `np.uint`, `np.float`). The agent intentionally stops early if those aliases are absent. Do not install the project's `ml/requirements.txt` into the isolated Gym environment without resolving that conflict. Pin and test Python, NumPy, Gym, protobuf, pyzmq, PyTorch, SciPy, and the checkpoint load together in the isolated environment.

**Network exposure:** the inspected upstream bridge binds `tcp://*:<port>`, even though the simulator connects to localhost. A local connection therefore does not make the listener loopback-only. Do not start it on a shared/untrusted host or network until an administrator has restricted that port with a host firewall or an isolated network. No firewall or system package changes are made by this experiment.

## Server integration sequence

1. Make a new experiment root, unpack the official ns-3.48 release there, and create its own Python environment. Keep the new root separate from `/app/ns-3-dev` and all existing experiment outputs.
2. Install/build the upstream `app-ns-3.36+` ns3-gym module **inside that new ns-3 tree only**, following its own instructions. Verify the resulting module exports `ns3/opengym-module.h`, links its ZeroMQ/protobuf dependencies, and can compile a minimal official example against ns-3.48. Stop if that compatibility check fails; do not infer compatibility from this repository's stub syntax check.
3. Copy `ns3-sim/honeycomb-sdwsn.cc` into `scratch/` and reconfigure. The same executable serves the CSV control and the Gym runs; it detects `ns3/opengym-module.h` at compile time. If an older checkout left `scratch/tldqn_gym/honeycomb-tldqn-gym.cc`, remove that folder.
4. Put `bigan_decisions_100_s<seed>.csv` in the read-only Gym scenario directory; it supplies attacker labels only. The CSV control additionally reads `bigan_windows_100_s<seed>.csv`. DTO/Bi-GAN decision files are not used. Restrict the chosen Gym port with the host firewall.
5. Use paired 14-second runs with identical network configuration. The live checkpoint is at t=8.3 s, leaving 5.7 seconds of post-reroute traffic and stopping before the legacy prevention event at t=15.3 s. Run CSV control with `--routeSource=csv --idsSource=none`; run Gym with `--routeSource=gym --idsSource=none --gymLiveAdaptive=true`.
6. For the Gym agent pass both `--expect-reroute --live-adaptive`; it logs phase-0 bootstrap routes and phase-1 live route decisions. Store control output at `runs/csv_control_adaptive_ns348_100_s<seed>/` and Gym output/audit at `runs/tldqn_live_adaptive_100_s<seed>/`. Each simulator `--outputDir` must be a new directory.
7. Confirm both processes exit successfully and the audit, `metrics.csv`, telemetry, and IDS snapshot are all present. A missing audit or metrics file is an incomplete run, not a zero-valued result.

The upstream ns3-gym module has built against the server's isolated ns-3.48 tree and the bootstrap route experiment ran there. The live-telemetry adaptive path is new and still needs its first server run; the local C++ check uses ns-3 headers plus a Gym declaration stub, so it does not replace that runtime validation.

## Run TLDQN live-adaptive

On the server, pull the latest branch, copy the simulator source into the isolated ns-3.48 scratch folder and rebuild after updating the source:

```sh
PROJECT="$HOME/experiments/sdwsn-tldqn"
NS3="$PROJECT/ns3-src/ns-3.48"
cd "$PROJECT"
git pull --ff-only origin feat/ai-ns3-integration
cp "$PROJECT/ns3-sim/honeycomb-sdwsn.cc" "$NS3/scratch/honeycomb-sdwsn.cc"
rm -rf "$NS3/scratch/tldqn_gym"   # old separate Gym copy, if present
cd "$NS3"
./ns3 configure --disable-examples
./ns3 build honeycomb-sdwsn -j 2
```

Use a 14-second same-build pair: the adaptive checkpoint is at 8.3 seconds, leaving 5.7 seconds of post-update traffic. (Live-adaptive runs do not schedule the 15.3-second prevention event.) Each `outputDir` must be new.

CSV control:

```sh
PROJECT="$HOME/experiments/sdwsn-tldqn"
NS3="$PROJECT/ns3-src/ns-3.48"
CSV_RUN="$PROJECT/ns3-sim/tldqn_gym/runs/csv_control_adaptive_ns348_100_s4"
mkdir -p "$CSV_RUN/telemetry"
cd "$NS3"
./ns3 run "honeycomb-sdwsn --numNodes=100 --seed=4 --simTime=14 --telemWindow=7.3 \
  --numUsers=10 --numPackets=50 --profile=paper --wifiStd=ac --maxRange=150 \
  --wdTimeout=0.1 --wdLate=1 \
  --aiDir=$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/scenarios \
  --routeDir=$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/routes \
  --routeSource=csv --idsSource=none --outputDir=$CSV_RUN --outCsv=$CSV_RUN/metrics.csv \
  --telemDir=$CSV_RUN/telemetry"
```

Gym agent, in the first terminal:

```sh
PROJECT="$HOME/experiments/sdwsn-tldqn"
GYM_RUN="$PROJECT/ns3-sim/tldqn_gym/runs/tldqn_live_adaptive_100_s4"
cd "$PROJECT"
.venv-gym/bin/python ns3-sim/tldqn_gym/agent.py --port 5555 --nodes 100 --seed 4 \
  --expect-reroute --live-adaptive --audit "$GYM_RUN/audit.json"
```

Gym simulator, in the second terminal:

```sh
PROJECT="$HOME/experiments/sdwsn-tldqn"
NS3="$PROJECT/ns3-src/ns-3.48"
GYM_RUN="$PROJECT/ns3-sim/tldqn_gym/runs/tldqn_live_adaptive_100_s4"
cd "$NS3"
./ns3 run "honeycomb-sdwsn --numNodes=100 --seed=4 --simTime=14 --telemWindow=7.3 \
  --numUsers=10 --numPackets=50 --profile=paper --wifiStd=ac --maxRange=150 \
  --wdTimeout=0.1 --wdLate=1 --routeSource=gym --openGymPort=5555 --gymLiveAdaptive=true \
  --aiDir=$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/scenarios \
  --idsSource=none --outputDir=$GYM_RUN"
```

Run the adaptive parity checker with `--mode adaptive` and `--control-dir` as shown below. The checker accepts network KPI differences, but requires matching pre-action input, live telemetry use, IDS-disabled counters and an applied reroute count consistent with the Gym audit.

## Compare and report

After transferring the same-build TLDQN-only CSV control and live Gym run into `ns3-sim/tldqn_gym/runs/` (include `metrics.csv` and `telemetry/` for the control; include `audit.json`, `metrics.csv`, and `telemetry/` for Gym), run:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python ns3-sim/tldqn_gym/check_parity.py \
  --audit ns3-sim/tldqn_gym/runs/tldqn_live_adaptive_100_s4/audit.json \
  --gym-dir ns3-sim/tldqn_gym/runs/tldqn_live_adaptive_100_s4 --mode adaptive \
  --control-dir ns3-sim/tldqn_gym/runs/csv_control_adaptive_ns348_100_s4
```

Adaptive parity requires initial routes to match the frozen baseline, pre-action telemetry/snapshot to match the same-build control, a nonzero live-measured-link count, IDS-disabled counters, and the route-change count in the audit to match the simulator's `reroute_changed`. KPI deltas are reported, not required to be zero. Archived Hybrid F2 results are not inputs to this TLDQN-only adaptive run.

The parity command exits nonzero unless route, live telemetry and action-application gates pass. Network KPI deltas are reported, not required to be zero. Results are shown in the root dashboard (next section). A mode or seed without a complete run stays marked as not run or pending, never as made-up metrics.

## Use the initial Research Console

The root `dashboard/index.html` is generated by `ml/build_dashboard.py`. Its "Mode eksperimen" selector holds the three modes: Baseline CSV, Adaptive live Gym, and Adaptive live Gym + sensor isolation (F2). Older configurations remain in source artifacts but are excluded from this dashboard snapshot. Copy `runs/csv_control_adaptive_ns348_100_s<seed>/` and `runs/tldqn_live_adaptive_100_s<seed>/` into this project checkout, then run:

```sh
.venv-gym/bin/python ml/build_dashboard.py
```

The generated console requires both control and Gym runs to show a seed. Its adaptive parity badge checks route action application and pre-action telemetry; KPI changes after t=8.3 are expected to be reported. The policy is frozen and uses measured NS-3 features at phase 1 with proxy fallback for unmeasured links. This mode does not run DTO/Bi-GAN actions.

Run one seed at a time first. Inspect the agent log's measured-link/fallback counts and per-flow next-hop changes, then review adaptive parity and network KPI deltas. Do not describe this limited adaptive TLDQN experiment as full paper reproduction or deployment-ready.

For the paired three-mode comparison including **TLDQN adaptive live Gym + Hybrid F2**, follow [TLDQN_GYM_HYBRID_F2_RUNBOOK.md](TLDQN_GYM_HYBRID_F2_RUNBOOK.md).