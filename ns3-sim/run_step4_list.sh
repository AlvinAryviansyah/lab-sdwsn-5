#!/usr/bin/env bash
# Runner sweep langkah 4 dari daftar skenario (docs/STEP4_HYBRID_IDS_DESIGN.md 11.10).
#
# Pemakaian (di server ns-3):
#   NS3_DIR=/app/ns-3-dev ./ns3-sim/run_step4_list.sh <daftar.txt> <status.csv>
#
# Tiap baris daftar (spasi; baris kosong/# diabaikan):
#   <n> <seed> <out_tag> <route_dir> <telem_dir> [argumen tambahan honeycomb-sdwsn ...]
# Path relatif terhadap $NS3_DIR. Keluaran sama dengan run_sweep.sh:
#   results/{metrics,timeseries,log}_<n>_s<seed><out_tag>.*  dan  <telem_dir>/...
#
# Berbeda dengan run_sweep.sh: run yang GAGAL TIDAK menghentikan daftar. Setiap run
# dicatat di <status.csv> (n,seed,out_tag,rc,detik), dan exit code akhir = jumlah gagal
# (0 = semua sukses). Tidak ada run yang dilewati diam-diam.
set -uo pipefail
NS3_DIR="${NS3_DIR:-/app/ns-3-dev}"
LIST="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
STATUS="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
cd "$NS3_DIR"
mkdir -p results
echo "n,seed,out_tag,rc,detik" > "$STATUS"
total=$(grep -cvE '^\s*(#|$)' "$LIST"); i=0; fail=0
while read -r n s tag rdir tdir extra; do
  [[ -z "${n:-}" || "$n" == \#* ]] && continue
  i=$(( i + 1 ))
  mkdir -p "$tdir"
  echo "[$i/$total] n=$n seed=$s tag=$tag"
  t0=$SECONDS
  ./ns3 run "honeycomb-sdwsn --profile=paper --numNodes=${n} --seed=${s} --outCsv=results/metrics_${n}_s${s}${tag}.csv --tsCsv=results/timeseries_${n}_s${s}${tag}.csv --routeDir=${rdir} --telemDir=${tdir} ${extra:-}" \
    > "results/log_${n}_s${s}${tag}.txt" 2>&1
  rc=$?
  echo "${n},${s},${tag},${rc},$(( SECONDS - t0 ))" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    fail=$(( fail + 1 ))
    echo "    GAGAL rc=$rc: lihat results/log_${n}_s${s}${tag}.txt"
  else
    echo "    selesai dalam $(( SECONDS - t0 )) s"
  fi
done < "$LIST"
echo "Selesai: $(( i - fail ))/$i sukses, $fail gagal. Status: $STATUS"
exit "$fail"
