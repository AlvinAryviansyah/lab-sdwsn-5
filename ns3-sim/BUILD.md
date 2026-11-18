# Build & Run di ns-3.48

Simulasi `honeycomb-sdwsn.cc` ditulis untuk **ns-3.48** (CMake / `./ns3`).
Modul yang dibutuhkan: `core, network, mobility, wifi, internet, energy,
flow-monitor, netanim, applications` — semuanya sudah ada di instalasi kamu.

## 0. Hasilkan keputusan AI (Python) — WAJIB sebelum simulasi

Bi-GAN dan TLDQN dilatih sungguhan di Python; ns-3 hanya membaca keputusannya
(sesuai paper: keputusan diambil di secondary controller / edge server).

```bash
# di mesin lokal (folder lab/):
.venv/bin/python ml/export_decisions.py --epochs 20 --seeds 5
# model tersimpan di ml/checkpoints/; untuk ekspor ulang tanpa melatih lagi:
#   .venv/bin/python ml/export_decisions.py --reuse --seeds 5
```

Model dilatih sekali; tiap seed = skenario berbeda (node malicious dan sampel
trafik berbeda) sehingga ulangan simulasi bermakna statistik.

Menghasilkan di `ns3-sim/results/`:
- `bigan_decisions_<n>_s<seed>.csv` — prediksi intrusi awal + ground truth tiap node
- `bigan_windows_<n>_s<seed>.csv`   — prediksi per window (metrik time-based)
- `tldqn_routes_<n>_s<seed>.csv`   — LEGACY (tidak dibaca NS-3 lagi; salinan lama di `archive/`)
- `ai_timing.csv`                  — waktu per keputusan (batch=1, median setelah warm-up)

Lalu ekspor **tabel next-hop TLDQN** (routing multi-hop, integrasi langkah 1):

```bash
.venv/bin/python ml/export_routes.py
# referensi pembanding (bukan metode): greedy progres terbesar
.venv/bin/python ml/export_routes.py --policy greedy --out-dir ns3-sim/results/routes_greedy
```

- `tldqn_nexthop_<n>_s<seed>.csv` — next-hop per (sensor, sink tujuan); node malicious
  diambil dari `bigan_decisions_<n>_s<seed>.csv` yang sama
- `tldqn_nexthop_meta.json`       — model + hash, asumsi, ringkasan per skenario

Verifikasi C++ tanpa server (header ns-3.48 asli, tanpa build):
`./ns3-sim/tools/syntax_check.sh`.

Salin semuanya ke `/app/ns-3-dev/results/` (lihat langkah 1). Simulasi akan
**berhenti dengan error** jika file ini tidak ada (sengaja, agar tidak diam-diam
memakai keputusan palsu).

## 1. Salin ke scratch

Di server ns-3 kamu (`/app/ns-3-dev`):

```bash
# dari mesin ini, kirim file ke server (ganti user@host sesuai milikmu):
scp ns3-sim/honeycomb-sdwsn.cc  lab@ns3-lab:/app/ns-3-dev/scratch/

# ATAU kalau sudah di server, salin manual ke:
#   /app/ns-3-dev/scratch/honeycomb-sdwsn.cc
```

Buat folder output dan salin file keputusan AI (program menulis ke `results/`):

```bash
cd /app/ns-3-dev
mkdir -p results
# dari mesin lokal:
scp ns3-sim/results/bigan_decisions_*_s*.csv ns3-sim/results/bigan_windows_*_s*.csv \
    ns3-sim/results/tldqn_nexthop_*_s*.csv \
    ns3-sim/results/ai_timing.csv  lab@ns3-lab:/app/ns-3-dev/results/
# (atau di server setelah git pull:
#  cp ns3-sim/results/{bigan_decisions,bigan_windows,tldqn_nexthop}_*_s*.csv \
#     ns3-sim/results/ai_timing.csv /app/ns-3-dev/results/
#  mkdir -p /app/ns-3-dev/results/routes_greedy && \
#  cp ns3-sim/results/routes_greedy/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_greedy/)
# referensi greedy via scp:
#   scp -r ns3-sim/results/routes_greedy lab@ns3-lab:/app/ns-3-dev/results/
```

> Catatan: `./ns3 run` mengeksekusi dari root `/app/ns-3-dev`, jadi folder
> `results/` relatif terhadap situ. Semua output (CSV, txt, xml) muncul di
> `/app/ns-3-dev/results/`.

## 2. Build

```bash
cd /app/ns-3-dev
./ns3 build honeycomb-sdwsn
```

Kalau ini build pertama setelah menambah scratch, cukup:

```bash
./ns3 build
```

## 3. Run (single, 100 node)

```bash
./ns3 run "honeycomb-sdwsn --numNodes=100 --simTime=300 --seed=1"
```

`--seed=N` memilih skenario AI `..._100_sN.csv` sekaligus seed RNG ns-3.

Profil simulasi (lihat `docs/PAPER_DEVIATIONS.md`):
- `--profile=paper` (default): Tabel 4-5 (600 s, ukuran paket 64..1024, 802.11ac
  80 MHz). **50 paket/node** (bukan 1000) dan TCP user -> cloud mati default karena
  batas memori; lihat `docs/PAPER_DEVIATIONS.md` bagian 4a.
- `--profile=code`: setara kode rilis penulis (300 s, 802.11a 6 Mbps, tanpa TCP).
- Jika `ChannelSettings`/802.11ac bermasalah: tambahkan `--wifiStd=a`.
- NetAnim mati secara default; nyalakan dengan `--anim=true`.

**Ukur waktu dulu** sebelum sweep penuh (compute kecil):

```bash
time ./ns3 run "honeycomb-sdwsn --numNodes=20  --seed=1"
time ./ns3 run "honeycomb-sdwsn --numNodes=100 --seed=1"
```

Jika run 100 node terlalu lama, kurangi beban dengan `--numPackets=200`
(dicatat sebagai deviasi) atau sapuan lebih sedikit (lihat di bawah).

Output yang dihasilkan di `results/`:
- `metrics.csv`                     — 9 metrik (termasuk lifetime, computation &
                                      control overhead) + confusion matrix Bi-GAN
                                      + confusion DTO + jumlah node terisolasi
- `PrivatekeyRegDevce.txt`          — private key device (3D Cube)
- `PrivatekeyRegUser.txt`           — private key user
- `Modified_Honeycomb_Structure.xml`— untuk NetAnim (Fig. 8)
- `flowmon.xml`                     — statistik FlowMonitor

## 4. Run sweep 20..100 node (untuk Fig. 9-17)

Paper mengevaluasi metrik terhadap jumlah node 20..100. Jalankan sweep 9 ukuran
jaringan x 5 seed (45 run) dengan skrip:

```bash
cd ~/sdwsn            # repo hasil git clone
NS3_DIR=/app/ns-3-dev ./ns3-sim/run_sweep.sh 3             # 3 seed, profil paper (600 s)
# hemat compute: titik node lebih sedikit
#   NODES="20 60 100" NS3_DIR=/app/ns-3-dev ./ns3-sim/run_sweep.sh 3
# saran: jalankan di tmux / nohup agar tidak putus
#   nohup env NS3_DIR=/app/ns-3-dev ./ns3-sim/run_sweep.sh 3 > sweep.log 2>&1 &
```

Skrip memeriksa kelengkapan CSV keputusan AI dulu, lalu menjalankan semua
kombinasi dan mencatat waktu tiap run di `results/sweep_times.csv`. Hasil: `results/metrics_<n>_s<seed>.csv` + `results/timeseries_<n>_s<seed>.csv` (log per run di
`results/log_<n>_s<seed>.txt`).

Arus radio sensor (idle/RX/CCA) bisa diubah lewat opsi
`--idleCurrentA`, `--rxCurrentA`, `--ccaBusyCurrentA` (default kelas CC2420).

## 4b. Telemetry langkah 2 (runbook server)

Definisi berkas ada di `docs/TELEMETRY.md`. Telemetry aktif secara default
(`--telemetry=true`) dan ditulis ke `--telemDir`. `run_sweep.sh` memakai
`results/telemetry${OUT_TAG}`.

```bash
# 0. kode + tabel tahap-1 (trust 0.5, tanpa label) ke ns-3
cd ~/sdwsn && git pull
cp ns3-sim/honeycomb-sdwsn.cc /app/ns-3-dev/scratch/
mkdir -p /app/ns-3-dev/results/routes_stage1
cp ns3-sim/results/routes_stage1/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage1/
cd /app/ns-3-dev && ./ns3 build honeycomb-sdwsn

# 1. pilot (cek baris "[Telemetry]" dan TIDAK ada "[PERINGATAN] telemetry_ip_forward_udp_total")
mkdir -p results/telemetry_pilot
./ns3 run "honeycomb-sdwsn --numNodes=20 --seed=1 --routeDir=results/routes_stage1 \
  --telemDir=results/telemetry_pilot --outCsv=results/metrics_20_s1_pilot.csv" 2>&1 | tail -n 25

# 2. rantai SEKUENSIAL (jangan paralel; memori server)
cd ~/sdwsn
nohup sh -c '
 env NS3_DIR=/app/ns-3-dev ROUTE_DIR=results/routes_stage1 OUT_TAG=_stage1 \
   ./ns3-sim/run_sweep.sh 3 > sweep_stage1.log 2>&1 &&
 env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage1 OUT_TAG=_stage1rep \
   ./ns3-sim/run_sweep.sh 1 > sweep_stage1rep.log 2>&1 &&
 env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage1 OUT_TAG=_notelem \
   EXTRA="--telemetry=false" ./ns3-sim/run_sweep.sh 1 > sweep_notelem.log 2>&1 &&
 env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage1 OUT_TAG=_ctrl0 \
   EXTRA="--grayholeDrop=0" ./ns3-sim/run_sweep.sh 3 > sweep_ctrl0.log 2>&1' &

# 3. simpan ke repo (lalu commit + push seperti langkah 1)
mkdir -p ns3-sim/results/step2
cp -r /app/ns-3-dev/results/telemetry_stage1 /app/ns-3-dev/results/telemetry_stage1rep \
      /app/ns-3-dev/results/telemetry_ctrl0 ns3-sim/results/step2/
cp /app/ns-3-dev/results/metrics_*_s*_{stage1,stage1rep,notelem,ctrl0}.csv \
   /app/ns-3-dev/results/log_*_s*_{stage1,stage1rep,notelem,ctrl0}.txt \
   /app/ns-3-dev/results/sweep_times_{stage1,stage1rep,notelem,ctrl0}.csv ns3-sim/results/step2/
```

| Rantai | Tujuan |
|---|---|
| `_stage1` | 27 skenario: telemetry tahap-1 (sumber trust) + validasi FlowMonitor/energi/agregasi |
| `_stage1rep` | run ulang seed 1 (n = 20, 60, 100): SHA-256 telemetry harus identik dengan `_stage1` |
| `_notelem` | `--telemetry=false`: metrik harus identik dengan `_stage1` (telemetry pasif) |
| `_ctrl0` | `--grayholeDrop=0`: rasio penerusan malicious harus mendekati normal (tanpa kebocoran label) |

Evaluasi di mesin lokal (label dipakai hanya di sini), lalu tahap-2:

```bash
S2=ns3-sim/results/step2; ALL="20 30 40 50 60 70 80 90 100"
.venv/bin/python ml/telemetry_eval.py --telem-dir $S2/telemetry_stage1 \
  --scenario-dir ns3-sim/results --metrics-dir $S2 --metrics-tag _stage1 \
  --nodes $ALL --seeds 1 2 3 --repeat-dir $S2/telemetry_stage1rep --passive-tag _notelem \
  --out ml/reports/telemetry_step2_stage1.json
.venv/bin/python ml/telemetry_eval.py --telem-dir $S2/telemetry_ctrl0 \
  --scenario-dir ns3-sim/results --metrics-dir $S2 --metrics-tag _ctrl0 \
  --nodes 20 60 100 --seeds 1 2 3 --out ml/reports/telemetry_step2_ctrl0.json
.venv/bin/python ml/telemetry_trust.py --telem-dir ns3-sim/results/step2/telemetry_stage1 \
  --out-dir ns3-sim/results/step2/trust_stage1 --nodes 20 30 40 50 60 70 80 90 100 --seeds 1 2 3
.venv/bin/python ml/export_routes.py --trust-source telemetry \
  --trust-dir ns3-sim/results/step2/trust_stage1 --out-dir ns3-sim/results/routes_stage2
.venv/bin/python ml/analyze_stage2_tables.py      # diagnosis tabel (label hanya evaluasi)
```

Batch server tahap-2. Binary baru menambah counter `telemetry_ip_forward_udp_delivered`
untuk verifikasi eksak FlowMonitor:

```bash
cd ~/sdwsn && git pull
cp ns3-sim/honeycomb-sdwsn.cc /app/ns-3-dev/scratch/
mkdir -p /app/ns-3-dev/results/routes_stage1 /app/ns-3-dev/results/routes_stage2
cp ns3-sim/results/routes_stage1/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage1/
cp ns3-sim/results/routes_stage2/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage2/
cd /app/ns-3-dev && ./ns3 build honeycomb-sdwsn && cd ~/sdwsn
nohup sh -c '
 env NS3_DIR=/app/ns-3-dev ROUTE_DIR=results/routes_stage2 OUT_TAG=_stage2 \
   ./ns3-sim/run_sweep.sh 3 > sweep_stage2.log 2>&1 &&
 env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage1 OUT_TAG=_stage1v2 \
   ./ns3-sim/run_sweep.sh 1 > sweep_stage1v2.log 2>&1' &
# setelah selesai:
cp -r /app/ns-3-dev/results/telemetry_stage2 /app/ns-3-dev/results/telemetry_stage1v2 \
      ns3-sim/results/step2/
cp /app/ns-3-dev/results/{metrics,timeseries}_*_s*_{stage2,stage1v2}.csv \
   /app/ns-3-dev/results/log_*_s*_{stage2,stage1v2}.txt \
   /app/ns-3-dev/results/sweep_times_{stage2,stage1v2}.csv \
   sweep_stage2.log sweep_stage1v2.log ns3-sim/results/step2/
```

| Rantai | Tujuan |
|---|---|
| `_stage2` | 27 skenario dgn trust telemetry; dibandingkan berpasangan dgn `_stage1` |
| `_stage1v2` | binary baru, tabel tahap-1: `delivered` = FlowMonitor eksak; SHA-256 telemetry node/link/audit harus identik dgn `_stage1` (counter baru pasif) |

## 4c. Langkah 4: Hybrid IDS (DTO + Bi-GAN) dan IPS, pilot

Desain dan keputusan: `docs/STEP4_HYBRID_IDS_DESIGN.md`. Opsi baru (opt-in):
`--idsSource=cpp|file|none` (default `cpp` = perilaku langkah 1–3) dan `--idsDir`.
Semua run langkah 4 memakai rute tahap-2 (`results/routes_stage2`), n = 20, 60, 100,
seed 1. Jalankan **berurutan**, satu tahap per kali. Jangan lanjut ke tahap berikutnya
sebelum hasil tahap sebelumnya diperiksa.

```bash
# P0. build + regresi default dan passivity --telemWindow
cd ~/sdwsn && git pull
cp ns3-sim/honeycomb-sdwsn.cc /app/ns-3-dev/scratch/
mkdir -p /app/ns-3-dev/results/routes_stage2
cp ns3-sim/results/routes_stage2/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage2/
cd /app/ns-3-dev && ./ns3 build honeycomb-sdwsn && cd ~/sdwsn
# WAJIB: pastikan binary memuat kode langkah 4 sebelum menjalankan apa pun
# (pilot pertama c757ba5 tanpa sengaja memakai binary lama: run A gagal "--idsSource")
grep -q 'idsSource    = "cpp"' /app/ns-3-dev/scratch/honeycomb-sdwsn.cc \
  && (cd /app/ns-3-dev && ./ns3 run "honeycomb-sdwsn --PrintHelp" 2>&1 | grep -q -- "--idsSource") \
  && echo "OK: binary langkah 4" || echo "STOP: binary/kode lama, jangan lanjut"
env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4reg \
  ./ns3-sim/run_sweep.sh 1 > sweep_s4reg.log 2>&1
env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4tw \
  EXTRA="--telemWindow=7.3" ./ns3-sim/run_sweep.sh 1 > sweep_s4tw.log 2>&1

# P1. run A: tanpa tindakan IDS, telemetry window 7.3 s (sumber bukti DTO)
env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4A \
  EXTRA="--idsSource=none --telemWindow=7.3" ./ns3-sim/run_sweep.sh 1 > sweep_s4A.log 2>&1

# simpan P0 + P1 ke repo, lalu commit + push (dilakukan pengguna)
mkdir -p ns3-sim/results/step4
cp -r /app/ns-3-dev/results/telemetry_s4reg /app/ns-3-dev/results/telemetry_s4tw \
      /app/ns-3-dev/results/telemetry_s4A ns3-sim/results/step4/
cp /app/ns-3-dev/results/{metrics,timeseries,log}_*_s1_{s4reg,s4tw,s4A}.* \
   /app/ns-3-dev/results/sweep_times_{s4reg,s4tw,s4A}.csv \
   sweep_s4reg.log sweep_s4tw.log sweep_s4A.log ns3-sim/results/step4/
```

Lokal (setelah P1): keputusan hybrid + tabel reroute untuk ketiga varian.

```bash
R=ns3-sim/results; S4=$R/step4
.venv/bin/python ml/hybrid_ids.py --telem-dir $S4/telemetry_s4A --scenario-dir $R \
  --route-dir $R/routes_stage2 --trust-dir $R/step2/trust_stage1 \
  --out-dir $S4/dec_F2 --nodes 20 60 100 --seeds 1 --fusion F2 --b-max 0
.venv/bin/python ml/hybrid_ids.py --telem-dir $S4/telemetry_s4A --scenario-dir $R \
  --route-dir $R/routes_stage2 --trust-dir $R/step2/trust_stage1 \
  --out-dir $S4/dec_F1 --nodes 20 60 100 --seeds 1 --fusion F1 --b-max 0
.venv/bin/python ml/hybrid_ids.py --telem-dir $S4/telemetry_s4A --scenario-dir $R \
  --route-dir $R/routes_stage2 --trust-dir $R/step2/trust_stage1 \
  --out-dir $S4/dec_K9_F2 --nodes 20 60 100 --seeds 1 --fusion F2 --b-max 0.8
# K15: bandingkan keputusan K9 vs pra-K9 pada skenario + window yang sama
for n in 20 60 100; do
  cmp -s $S4/dec_F2/hybrid_decisions_${n}_s1.csv $S4/dec_K9_F2/hybrid_decisions_${n}_s1.csv \
    && echo "n=$n K9 = pra-K9" || echo "n=$n K9 BERBEDA"
done
# lalu commit + push dec_F2, dec_F1, dec_K9_F2 (dilakukan pengguna)
```

```bash
# P2. run B (server): replay skenario yang sama + keputusan pada t = 8.3 s
cd ~/sdwsn && git pull
mkdir -p /app/ns-3-dev/results/step4 && cp -r ns3-sim/results/step4/dec_* /app/ns-3-dev/results/step4/
# K9_F2 hanya dijalankan bila keputusannya berbeda dari F2 (K15)
VARIANTS="F2 F1"
for n in 20 60 100; do
  cmp -s ns3-sim/results/step4/dec_F2/hybrid_decisions_${n}_s1.csv \
         ns3-sim/results/step4/dec_K9_F2/hybrid_decisions_${n}_s1.csv || VARIANTS="F2 F1 K9_F2"
done
echo "varian run B: $VARIANTS"
for V in $VARIANTS; do
  env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4B_$V \
    EXTRA="--idsSource=file --idsDir=results/step4/dec_$V --telemWindow=7.3" \
    ./ns3-sim/run_sweep.sh 1 > sweep_s4B_$V.log 2>&1 || break
done
cp -r /app/ns-3-dev/results/telemetry_s4B_* ns3-sim/results/step4/
cp /app/ns-3-dev/results/{metrics,timeseries,log}_*_s1_s4B_*.* \
   /app/ns-3-dev/results/sweep_times_s4B_*.csv sweep_s4B_*.log ns3-sim/results/step4/
```

Blok P0/P1/P2 ditulis untuk bash di server (brace expansion dan word splitting
`$VARIANTS`). Blok lokal kompatibel dengan zsh. Pada evaluasi lokal di bawah, lewati
`K9_F2` bila varian itu tidak dijalankan di P2.

| Tahap | Gerbang (wajib lolos sebelum lanjut) |
|---|---|
| P0 `_s4reg` | `metrics_*` identik dengan `step2/*_stage2` **kecuali** `rt_compute_ms` dan `computation_overhead_percent` (waktu-dinding, berbeda setiap run; dilaporkan); `timeseries_*` dan telemetry identik byte (default `cpp` tidak berubah) |
| P0 `_s4tw` | `metrics_*` identik dengan `_stage2` kecuali dua baris waktu-dinding (`--telemWindow` pasif) |
| P1 `_s4A` | log ada baris `[IDS] snapshot pra-tindakan`; tidak ada error |
| P2 `_s4B_*` | `hybrid_eval.py determinism` A vs B **LULUS** (snapshot T_ids byte-identik + masukan DTO window 0 identik). Bila gagal: berhenti dan investigasi |

```bash
S4=ns3-sim/results/step4; S2=ns3-sim/results/step2
for n in 20 60 100; do
  .venv/bin/python ml/hybrid_eval.py identical --metrics --a $S2/metrics_${n}_s1_stage2.csv --b $S4/metrics_${n}_s1_s4reg.csv
  .venv/bin/python ml/hybrid_eval.py identical --a $S2/timeseries_${n}_s1_stage2.csv --b $S4/timeseries_${n}_s1_s4reg.csv
  .venv/bin/python ml/hybrid_eval.py identical --metrics --a $S2/metrics_${n}_s1_stage2.csv --b $S4/metrics_${n}_s1_s4tw.csv
  for k in telemetry telemetry_links watchdog_audit; do
    cmp $S2/telemetry_stage2/${k}_${n}_s1.csv $S4/telemetry_s4reg/${k}_${n}_s1.csv && echo "OK $k $n"
  done
done
for V in F2 F1 K9_F2; do
  .venv/bin/python ml/hybrid_eval.py determinism --dir-a $S4/telemetry_s4A \
    --dir-b $S4/telemetry_s4B_$V --nodes 20 60 100 --out ml/reports/step4_pilot_determinism_$V.json
  .venv/bin/python ml/hybrid_eval.py evaluate --dec-dir $S4/dec_$V --scenario-dir ns3-sim/results \
    --metrics-a "$S4/metrics_{tag}_s4A.csv" --metrics-b "$S4/metrics_{tag}_s4B_$V.csv" \
    --nodes 20 60 100 --out ml/reports/step4_pilot_eval_$V.json
done
```

Sweep penuh (27 skenario + ctrl0) **hanya setelah persetujuan eksplisit** (K18).

### Pilot ulang r2: binary dengan PDR sumber jujur (`benign_*`)

Binary baru hanya menambah baris `benign_tx_packets`, `benign_rx_packets`,
`benign_flows`, `benign_pdr_defined`, dan `benign_pdr_percent` (mode `file`/`none`;
`nan` bila tx = 0). Tag baru `_s4r2*` dipakai agar hasil pilot sebelumnya tidak
tertimpa. Keputusan `dec_*` yang sudah ada dipakai ulang. Gerbang `same-inputs`
(lokal) membuktikan bahwa run A baru identik dengan run A yang menjadi dasar `dec_*`.
Bila gerbang itu gagal, hasil run B r2 tidak sah.

```bash
# server: build + pengaman + P0 + P1 + P2 (satu batch, berurutan)
cd ~/sdwsn && git pull && git log --oneline -1
cp ns3-sim/honeycomb-sdwsn.cc /app/ns-3-dev/scratch/
mkdir -p /app/ns-3-dev/results/routes_stage2 /app/ns-3-dev/results/step4
cp ns3-sim/results/routes_stage2/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage2/
cp -r ns3-sim/results/step4/dec_F2 ns3-sim/results/step4/dec_F1 ns3-sim/results/step4/dec_K9_F2 \
      /app/ns-3-dev/results/step4/
cd /app/ns-3-dev && ./ns3 build honeycomb-sdwsn && cd ~/sdwsn
grep -q 'benign_pdr_percent' /app/ns-3-dev/scratch/honeycomb-sdwsn.cc \
  && (cd /app/ns-3-dev && ./ns3 run "honeycomb-sdwsn --PrintHelp" 2>&1 | grep -q -- "--idsSource") \
  && echo "OK: binary r2" || echo "STOP: binary/kode lama, jangan lanjut"
env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4r2reg \
  ./ns3-sim/run_sweep.sh 1 > sweep_s4r2reg.log 2>&1
env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4r2tw \
  EXTRA="--telemWindow=7.3" ./ns3-sim/run_sweep.sh 1 > sweep_s4r2tw.log 2>&1
env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4r2A \
  EXTRA="--idsSource=none --telemWindow=7.3" ./ns3-sim/run_sweep.sh 1 > sweep_s4r2A.log 2>&1
for V in F2 F1 K9_F2; do
  env NS3_DIR=/app/ns-3-dev NODES="20 60 100" ROUTE_DIR=results/routes_stage2 OUT_TAG=_s4r2B_$V \
    EXTRA="--idsSource=file --idsDir=results/step4/dec_$V --telemWindow=7.3" \
    ./ns3-sim/run_sweep.sh 1 > sweep_s4r2B_$V.log 2>&1 || break
done
grep -H -E "GAGAL|Selesai" sweep_s4r2*.log            # setiap berkas: "Selesai", tanpa "GAGAL"
mkdir -p ns3-sim/results/step4/r2
cp -r /app/ns-3-dev/results/telemetry_s4r2* ns3-sim/results/step4/r2/
cp /app/ns-3-dev/results/{metrics,timeseries,log}_*_s1_s4r2*.* \
   /app/ns-3-dev/results/sweep_times_s4r2*.csv sweep_s4r2*.log ns3-sim/results/step4/r2/
git add ns3-sim/results/step4/r2 && git commit -m "Pilot ulang langkah 4 r2 (benign PDR)" && git push
```

Gerbang lokal r2 (semua harus lulus; bila ada yang gagal: berhenti dan investigasi):

```bash
S4=ns3-sim/results/step4; R2=$S4/r2; S2=ns3-sim/results/step2
for n in 20 60 100; do
  .venv/bin/python ml/hybrid_eval.py identical --metrics --a $S2/metrics_${n}_s1_stage2.csv --b $R2/metrics_${n}_s1_s4r2reg.csv
  .venv/bin/python ml/hybrid_eval.py identical --a $S2/timeseries_${n}_s1_stage2.csv --b $R2/timeseries_${n}_s1_s4r2reg.csv
  .venv/bin/python ml/hybrid_eval.py identical --metrics --a $S2/metrics_${n}_s1_stage2.csv --b $R2/metrics_${n}_s1_s4r2tw.csv
  for k in telemetry telemetry_links watchdog_audit; do
    cmp $S2/telemetry_stage2/${k}_${n}_s1.csv $R2/telemetry_s4r2reg/${k}_${n}_s1.csv && echo "OK $k $n"
  done
done
for V in F2 F1 K9_F2; do
  .venv/bin/python ml/hybrid_eval.py same-inputs --dec-dir $S4/dec_$V --telem-dir $R2/telemetry_s4r2A \
    --nodes 20 60 100 --out ml/reports/step4_r2_same_inputs_$V.json
  .venv/bin/python ml/hybrid_eval.py determinism --dir-a $R2/telemetry_s4r2A --dir-b $R2/telemetry_s4r2B_$V \
    --nodes 20 60 100 --out ml/reports/step4_r2_determinism_$V.json
  .venv/bin/python ml/hybrid_eval.py applied --dec-dir $S4/dec_$V --metrics-b "$R2/metrics_{tag}_s4r2B_$V.csv" \
    --log-b "$R2/log_{tag}_s4r2B_$V.txt" --nodes 20 60 100 --out ml/reports/step4_r2_applied_$V.json
  .venv/bin/python ml/hybrid_eval.py evaluate --dec-dir $S4/dec_$V --scenario-dir ns3-sim/results \
    --metrics-a "$R2/metrics_{tag}_s4r2A.csv" --metrics-b "$R2/metrics_{tag}_s4r2B_$V.csv" \
    --nodes 20 60 100 --out ml/reports/step4_r2_eval_$V.json
done
```

## 4d. Langkah 4: sweep penuh (stage2 27 + ctrl0 9)

Runner `ns3-sim/run_step4_list.sh`: run yang gagal **tidak** menghentikan daftar. Setiap
run dicatat di berkas status (`rc`), dan exit code = jumlah gagal. ctrl0 memakai
`routes_stage1` + `--grayholeDrop=0` (sama dengan langkah 2). Hasil ke
`ns3-sim/results/step4/full/`.

```bash
# F1. run A (server): 36 run tanpa tindakan IDS
cd ~/sdwsn && git pull && git log --oneline -1
cp ns3-sim/honeycomb-sdwsn.cc /app/ns-3-dev/scratch/
mkdir -p /app/ns-3-dev/results/routes_stage2 /app/ns-3-dev/results/routes_stage1
cp ns3-sim/results/routes_stage2/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage2/
cp ns3-sim/results/routes_stage1/tldqn_nexthop_*_s*.csv /app/ns-3-dev/results/routes_stage1/
cd /app/ns-3-dev && ./ns3 build honeycomb-sdwsn && cd ~/sdwsn
grep -q 'benign_pdr_percent' /app/ns-3-dev/scratch/honeycomb-sdwsn.cc && echo "OK: binary" || echo "STOP"
./ns3-sim/run_step4_list.sh ns3-sim/step4_lists/runA.txt status_runA.csv > sweep_s4fA.log 2>&1
echo "gagal = $?"; tail -1 sweep_s4fA.log
mkdir -p ns3-sim/results/step4/full
cp -r /app/ns-3-dev/results/step4f/telemetry_s4fA /app/ns-3-dev/results/step4f/telemetry_s4cA \
      ns3-sim/results/step4/full/
cp /app/ns-3-dev/results/{metrics,timeseries,log}_*_s*_{s4fA,s4cA}.* \
   status_runA.csv sweep_s4fA.log ns3-sim/results/step4/full/
git add ns3-sim/results/step4/full && git commit -m "Langkah 4 sweep penuh: run A" && git push
```

Setelah run A di-push, keputusan F2/F1/K9_F2 dan daftar run B (`runB.txt`) dibuat lokal
(K9_F2 hanya untuk skenario yang isolasi atau reroute-nya berbeda dari F2), lalu
di-push. Run B:

```bash
# F2. run B (server)
cd ~/sdwsn && git pull && git log --oneline -1
mkdir -p /app/ns-3-dev/results/step4f && cp -r ns3-sim/results/step4/full/dec_* /app/ns-3-dev/results/step4f/
./ns3-sim/run_step4_list.sh ns3-sim/step4_lists/runB.txt status_runB.csv > sweep_s4fB.log 2>&1
echo "gagal = $?"; tail -1 sweep_s4fB.log
cp -r /app/ns-3-dev/results/step4f/telemetry_s4fB_* /app/ns-3-dev/results/step4f/telemetry_s4cB_* \
      ns3-sim/results/step4/full/ 2>/dev/null
cp /app/ns-3-dev/results/{metrics,timeseries,log}_*_s*_{s4fB,s4cB}_*.* \
   status_runB.csv sweep_s4fB.log ns3-sim/results/step4/full/
git add ns3-sim/results/step4/full && git commit -m "Langkah 4 sweep penuh: run B" && git push
```

## 5. Lihat animasi (opsional)

Buka `results/Modified_Honeycomb_Structure.xml` di NetAnim:

```bash
cd /app/ns-3-dev
./ns3 run netanim 2>/dev/null || true   # atau jalankan binary NetAnim langsung
# lalu File -> Open -> results/Modified_Honeycomb_Structure.xml
```

## 6. Ambil hasil ke mesin ini untuk plotting

```bash
# dari mesin lokal:
scp 'lab@ns3-lab:/app/ns-3-dev/results/metrics_*.csv'  ml/../ns3-sim/results/
```

Lalu plot dengan `ml/metrics_plots.py` (lihat `ml/`).

## Troubleshooting

- **`fatal error: ns3/energy-module.h`** — modul energy ada tapi mungkin perlu
  di-enable. Cek: `./ns3 configure --enable-modules=...` biasanya tak perlu;
  energy default ter-build. Kalau error, jalankan `./ns3 configure` lalu build ulang.
- **Namespace energy** — ns-3.48 memakai `ns3::energy::BasicEnergySourceHelper`.
  Sudah dipakai di kode. Kalau versimu masih `ns3::BasicEnergySourceHelper`
  (tanpa sub-namespace), hapus `energy::` pada baris energy di `main()`.
- **`WIFI_STANDARD_80211a` tidak dikenal** — seharusnya ada di ns-3.48.
  Alternatif: `WIFI_STANDARD_80211g`.
- **NetAnim warning posisi** — aman diabaikan; XML tetap tertulis.
