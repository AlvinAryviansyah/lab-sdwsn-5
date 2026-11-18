#!/usr/bin/env bash
# ============================================================================
#  run_three_modes.sh -- jalankan 3 mode dashboard untuk seed 4-6 secara bersih.
#
#  Per seed (berurutan, satu port Gym):
#    1. Mode 1  Baseline CSV            (--routeSource=csv --idsSource=none)
#    2. Mode 2  Adaptive live Gym       (agen di background + simulator) + parity
#    3. F2      prediksi Bi-GAN + keputusan hybrid dari telemetry Mode 2
#    4. Mode 3  Adaptive Gym + isolasi  (agen di background + simulator) + parity
#  Lalu ml/build_dashboard.py.
#
#  "Cleansing": run lama untuk seed yang dipilih DIPINDAHKAN (bukan dihapus) ke
#  ns3-sim/tldqn_gym/runs_archive/<waktu>/ sebelum mulai. Berhenti di kegagalan
#  pertama; log agen/simulator ada di folder run masing-masing.
#
#  Pemakaian (di server):
#    bash ns3-sim/tldqn_gym/run_three_modes.sh              # seed 4 5 6
#    SEEDS="5" bash ns3-sim/tldqn_gym/run_three_modes.sh    # satu seed saja
#    NO_BUILD=1 ...                                         # lewati ./ns3 build
#    DRY_RUN=1 ...                                          # cetak perintah saja
# ============================================================================
set -euo pipefail

PROJECT="${PROJECT:-$HOME/experiments/sdwsn-tldqn}"
NS3="${NS3:-$PROJECT/ns3-src/ns-3.48}"
PY="${PY:-$PROJECT/.venv-gym/bin/python}"
PORT="${PORT:-5555}"
SEEDS="${SEEDS:-4 5 6}"
RUNS="$PROJECT/ns3-sim/tldqn_gym/runs"
SCENARIOS="$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/scenarios"
ROUTES="$PROJECT/ns3-sim/results/bigan_pilot_test_4_6/routes"
BIGAN_RUN_ID="pilot_20261107_211217"
BIGAN_MODEL="$PROJECT/ml/checkpoints/bigan_ns3_pilot/$BIGAN_RUN_ID/model.pt"
BIGAN_MODEL_SHA256="1cb24041e96aec2bf5d494b087080ce4cc689fca0c80c730c09ea077a28084f7"
THRESHOLD="0.4741064757"
TARGET="scratch/honeycomb-sdwsn"
COMMON="--numNodes=100 --simTime=14 --telemWindow=7.3 --numUsers=10 --numPackets=50 \
--profile=paper --wifiStd=ac --maxRange=150 --wdTimeout=0.1 --wdLate=1 --aiDir=$SCENARIOS"

AGENT_PID=""
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mGAGAL: %s\033[0m\n' "$*" >&2; exit 1; }
run()  { if [[ -n "${DRY_RUN:-}" ]]; then printf '+ %s\n' "$*"; else "$@"; fi; }
cleanup() { if [[ -n "$AGENT_PID" ]] && kill -0 "$AGENT_PID" 2>/dev/null; then kill "$AGENT_PID"; fi; }
trap cleanup EXIT

# ---- port Gym harus bebas: di ns3-gym ini AGEN yang bind tcp://*:PORT ------------
# Agen lain yang masih hidup (mis. sisa run manual) memegang port; agen baru gagal bind
# dan simulator tersambung ke agen yang salah. Tunggu sebentar, lalu gagal dgn jelas.
port_free() {
  "$PY" - "$PORT" <<'PYEOF'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # abaikan TIME_WAIT run sebelumnya
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PYEOF
}
require_port_free() {
  [[ -n "${DRY_RUN:-}" ]] && return
  for _ in $(seq 1 15); do port_free && return; sleep 1; done
  echo "Proses yang mungkin memegang port $PORT:" >&2
  pgrep -af 'agent.py|honeycomb-sdwsn' >&2 || true
  fail "port $PORT masih dipakai. Hentikan agen/simulator lama: pkill -f ns3-sim/tldqn_gym/agent.py"
}
# Agen sudah listen? TANPA bind (bind uji coba bisa merebut port saat agen sedang
# bind -> agen gagal). Linux: ss (baca saja); cadangan: coba connect.
port_listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -Hltn "sport = :$PORT" 2>/dev/null | grep -q .
  else
    "$PY" - "$PORT" <<'PYEOF'
import socket, sys
try:
    socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.5).close()
except OSError:
    sys.exit(1)
PYEOF
  fi
}

show_logs() {   # show_logs <run_root>
  local f
  for f in "$1/agent.log" "$1/simulator.log"; do
    [[ -f "$f" ]] && { printf '\n----- %s (akhir)\n' "$f" >&2; tail -20 "$f" >&2; }
  done
  return 0
}

# ---- prasyarat -------------------------------------------------------------
say "Cek prasyarat"
[[ -x "$PY" ]] || fail "python Gym tidak ada: $PY"
[[ -d "$NS3" ]] || fail "tree ns-3 tidak ada: $NS3"
[[ -d "$SCENARIOS" && -d "$ROUTES" ]] || fail "input skenario/rute tidak ada di $SCENARIOS / $ROUTES"
cmp -s "$PROJECT/ns3-sim/honeycomb-sdwsn.cc" "$NS3/scratch/honeycomb-sdwsn.cc" ||
  fail "scratch/honeycomb-sdwsn.cc beda dgn repo; jalankan: cp $PROJECT/ns3-sim/honeycomb-sdwsn.cc $NS3/scratch/"
[[ ! -e "$NS3/scratch/tldqn_gym" && ! -e "$NS3/scratch/tldqn_csv_baseline" ]] ||
  fail "salinan lama di $NS3/scratch (tldqn_gym / tldqn_csv_baseline) membuat target ambigu; pindahkan dulu"
"$PY" -c "import numpy as np, sys; sys.exit(0 if all(hasattr(np, n) for n in ('int','uint','float')) else 1)" ||
  fail "NumPy di .venv-gym tidak punya alias np.int/np.uint/np.float (ns3-gym akan rusak)"
"$PY" -c "import sklearn, pandas, scipy, torch, ns3gym" ||
  fail "dependensi kurang di .venv-gym (butuh sklearn, pandas, scipy, torch, ns3gym)"
[[ -f "$BIGAN_MODEL" ]] || fail "checkpoint Bi-GAN tidak ada: $BIGAN_MODEL (scp dari laptop, lihat runbook)"
[[ "$(sha256sum "$BIGAN_MODEL" | cut -d' ' -f1)" == "$BIGAN_MODEL_SHA256" ]] ||
  fail "hash checkpoint Bi-GAN tidak cocok: $BIGAN_MODEL"
require_port_free

cd "$NS3"
if [[ -z "${NO_BUILD:-}" ]]; then run ./ns3 build "$TARGET" -j 2; fi
if [[ -z "${DRY_RUN:-}" ]]; then
  ./ns3 run "$TARGET --PrintHelp" | grep -q -- '--routeSource' ||
    fail "binary tidak punya --routeSource (build lama?)"
fi

# ---- cleansing: arsipkan run lama seed terpilih --------------------------------
ARCHIVE="$PROJECT/ns3-sim/tldqn_gym/runs_archive/$(date +%Y%m%d_%H%M%S)"
say "Arsipkan run lama -> $ARCHIVE"
moved=0
shopt -s nullglob
for seed in $SEEDS; do
  for old in "$RUNS"/csv_control_adaptive_ns348_100_s"$seed"* \
             "$RUNS"/tldqn_live_adaptive_100_s"$seed"* \
             "$RUNS"/tldqn_live_hybrid_f2_100_s"$seed"* \
             "$RUNS"/mode1_s"$seed".log; do
    [[ -e "$old" ]] || continue            # path literal (tanpa wildcard) lolos dari nullglob
    run mkdir -p "$ARCHIVE"
    run mv "$old" "$ARCHIVE/"
    moved=$((moved + 1))
  done
done
shopt -u nullglob
echo "  $moved folder dipindahkan (tidak ada yang dihapus)."

# ---- satu run Gym: agen di background, simulator di foreground ------------------
gym_run() {   # gym_run <run_root> <seed> <flag simulator tambahan...>
  local root="$1" seed="$2"; shift 2
  run mkdir -p "$root"
  require_port_free
  if [[ -n "${DRY_RUN:-}" ]]; then
    printf '+ (background) %s agent.py --seed %s --audit %s/audit.json\n' "$PY" "$seed" "$root"
    printf '+ ./ns3 run "%s %s --seed=%s --routeSource=gym --openGymPort=%s --gymLiveAdaptive=true %s --outputDir=%s/ns3"\n' \
      "$TARGET" "$COMMON" "$seed" "$PORT" "$*" "$root"
    return
  fi
  ( cd "$PROJECT" && exec "$PY" ns3-sim/tldqn_gym/agent.py --port "$PORT" --nodes 100 \
      --seed "$seed" --expect-reroute --live-adaptive --audit "$root/audit.json" ) \
      >"$root/agent.log" 2>&1 &
  AGENT_PID=$!
  # Tunggu agen siap (bind port) sebelum simulator mulai; gagal bind = berhenti.
  local ready=""
  for _ in $(seq 1 60); do
    if grep -q 'Cannot bind' "$root/agent.log" 2>/dev/null; then show_logs "$root"
      fail "agen gagal bind port $PORT (dipakai proses lain)"; fi
    kill -0 "$AGENT_PID" 2>/dev/null || { show_logs "$root"; fail "agen berhenti sebelum simulator mulai"; }
    if port_listening; then ready=1; break; fi   # agen ini sudah listen
    sleep 1
  done
  [[ -n "$ready" ]] || { show_logs "$root"; fail "agen tidak membuka port $PORT dalam 60 s"; }
  # shellcheck disable=SC2086
  if ! ./ns3 run "$TARGET $COMMON --seed=$seed --routeSource=gym --openGymPort=$PORT \
        --gymLiveAdaptive=true $* --outputDir=$root/ns3" >"$root/simulator.log" 2>&1; then
    show_logs "$root"; fail "simulator gagal (log: $root/simulator.log)"
  fi
  if ! wait "$AGENT_PID"; then
    AGENT_PID=""; show_logs "$root"; fail "agen gagal (log: $root/agent.log)"
  fi
  AGENT_PID=""
  local f missing=""
  for f in "$root/audit.json" "$root/ns3/metrics.csv"; do [[ -f "$f" ]] || missing+=" $f"; done
  if [[ -n "$missing" ]]; then show_logs "$root"; fail "run tidak lengkap; tidak ada:$missing"; fi
}

parity() {   # parity <audit> <gym_dir> <control_dir> <mode> <log>
  if [[ -n "${DRY_RUN:-}" ]]; then printf '+ check_parity.py --mode %s\n' "$4"; return; fi
  if ! ( cd "$PROJECT" && PYTHONDONTWRITEBYTECODE=1 "$PY" ns3-sim/tldqn_gym/check_parity.py \
        --audit "$1" --gym-dir "$2" --control-dir "$3" --mode "$4" ) >"$5"; then
    tail -20 "$5"; fail "parity $4 tidak lolos (detail: $5)"
  fi
  echo "  parity $4: pass  ($5)"
}

# ---- per seed ---------------------------------------------------------------
for seed in $SEEDS; do
  CSV_RUN="$RUNS/csv_control_adaptive_ns348_100_s$seed"
  ADAPTIVE_RUN="$RUNS/tldqn_live_adaptive_100_s$seed"
  HYBRID_RUN="$RUNS/tldqn_live_hybrid_f2_100_s$seed"

  say "Seed $seed · Mode 1 · Baseline CSV"
  if [[ -n "${DRY_RUN:-}" ]]; then
    printf '+ ./ns3 run "%s %s --seed=%s --routeSource=csv ..."\n' "$TARGET" "$COMMON" "$seed"
  else
    mkdir -p "$(dirname "$CSV_RUN")"
    ./ns3 run "$TARGET $COMMON --seed=$seed --routeDir=$ROUTES --routeSource=csv \
      --idsSource=none --outputDir=$CSV_RUN --telemDir=$CSV_RUN/telemetry" \
      >"$RUNS/mode1_s$seed.log" 2>&1 || { tail -30 "$RUNS/mode1_s$seed.log"; fail "Mode 1 seed $seed"; }
    mv "$RUNS/mode1_s$seed.log" "$CSV_RUN/simulator.log"
    [[ -f "$CSV_RUN/metrics.csv" ]] || fail "Mode 1 seed $seed tanpa metrics.csv"
  fi

  say "Seed $seed · Mode 2 · Adaptive live Gym"
  gym_run "$ADAPTIVE_RUN" "$seed" --idsSource=none
  parity "$ADAPTIVE_RUN/audit.json" "$ADAPTIVE_RUN/ns3" "$CSV_RUN" adaptive \
         "$ADAPTIVE_RUN/parity.json"

  say "Seed $seed · F2 · prediksi Bi-GAN + keputusan hybrid"
  run mkdir -p "$HYBRID_RUN"
  # Rantai && eksplisit: set -e tidak berlaku di dalam subshell yang diikuti ||.
  ( cd "$PROJECT" &&
    run "$PY" ml/bigan_ns3_pilot.py predict --run-id "$BIGAN_RUN_ID" \
      --telem-dir "$ADAPTIVE_RUN/ns3/telemetry" --nodes 100 --seed "$seed" \
      --threshold "$THRESHOLD" --out-dir "$HYBRID_RUN/predictions" &&
    run "$PY" ml/hybrid_ids.py --telem-dir "$ADAPTIVE_RUN/ns3/telemetry" \
      --scenario-dir "$SCENARIOS" --bigan-pred-dir "$HYBRID_RUN/predictions" \
      --route-dir "$ROUTES" --out-dir "$HYBRID_RUN/decisions" --nodes 100 \
      --seeds "$seed" --fusion F2 ) || fail "keputusan F2 seed $seed"

  say "Seed $seed · Mode 3 · Adaptive Gym + isolasi sensor"
  gym_run "$HYBRID_RUN" "$seed" --idsSource=file --idsDir="$HYBRID_RUN/decisions" \
          --hybridPilotBigan=true
  parity "$HYBRID_RUN/audit.json" "$HYBRID_RUN/ns3" "$ADAPTIVE_RUN/ns3" adaptive_hybrid \
         "$HYBRID_RUN/parity.json"
done

say "Build dashboard"
( cd "$PROJECT" && run "$PY" ml/build_dashboard.py ) || fail "build dashboard"
say "Selesai: seed [$SEEDS] x 3 mode lolos parity; dashboard/index.html diperbarui."
