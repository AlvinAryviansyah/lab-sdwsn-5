# Langkah 4: hasil sweep penuh (dihasilkan `ml/step4_full.py report`)

Data: `ns3-sim/results/step4/full/`. JSON lengkap: `ml/reports/step4_full_report.json`.
Desain dan keputusan: `docs/STEP4_HYBRID_IDS_DESIGN.md` (bagian 11).

## Ringkasan (ditulis tangan; bagian setelahnya dihasilkan skrip)

- **Cakupan.** stage2: 27 skenario (n = 20…100 × seed 1–3); ctrl0: 9 skenario (n =
  20/60/100 × seed 1–3, tanpa grayhole). Total 36 run A + 77 run B = **113 run NS-3,
  0 gagal**. K9_F2 disimulasikan pada 5 skenario stage2. 31 skenario K9_F2 lainnya
  memakai simulasi F2, karena isolasi dan reroute-nya identik.
- **Gerbang.** Determinisme A vs B dan `applied` lulus di **108/108** kombinasi
  skenario × varian.
- **Integritas data.** Dataset run B resmi adalah pass pertama yang lengkap (`c02ac4f`,
  77/77). Pass kedua yang tumpang-tindih (`14a1b2d`, `d71aa9f`) disalin saat masih
  berjalan: 7 log terpotong dan berkas status tertimpa. Metriknya hanya berbeda di baris
  waktu-dinding. Pass itu tetap ada di riwayat git dan **tidak** dipakai.
- **F2 (utama) pada stage2.**
  - DTO dini (bukti [0, 7.3 s)): 32 TP, 0 FP (P 1.000, R 0.198). Hampir sama dengan DTO
    langkah 3 akhir run (33 TP).
  - Tidak ada node jujur yang diisolasi, dan tidak ada jalur gagal.
  - PDR sumber jujur +1.14 pp (Wilcoxon p = 0.0003; 17 naik, 0 turun, 10 sama).
  - Paket jujur diterima 70 476 → 71 424 (+948). Drop grayhole 3427 → 1952 (−1475).
  - Biaya: latency +0.010 ms, throughput −0.24 kbps (trafik flooding penyerang yang
    diisolasi berhenti).
- **F1 (eksperimental, tidak disebut paper).**
  - Mengisolasi 17 node jujur (FP Bi-GAN), sehingga 440 paket jujur tidak pernah
    terkirim.
  - Paket jujur diterima hanya +481, kira-kira setengah dari F2. Rasio PDR jujurnya
    hampir sama dengan F2 (+1.16 vs +1.14 pp).
  - Throughput −2.0 kbps dan latency +0.044 ms (keduanya p < 0.001).
  - Pada ctrl0 (tanpa grayhole), F1 tetap mengisolasi 6 node jujur, dengan PDR jujur −0.0014 pp.
- **K9_F2 (pembanding).** Lebih sedikit TP DTO (25 vs 32), sehingga manfaatnya lebih
  kecil (paket jujur +784).
- **ctrl0.** F2 dan K9_F2 tidak mengisolasi apa pun (DTO 0 FP), sehingga tidak ada efek.
- **Koreksi tafsiran pilot (11.9 butir 1).** Pada 3 skenario pilot, kenaikan paket jujur
  kebetulan sama dengan penurunan drop grayhole. Pada sweep penuh tidak sama (+948 vs
  −1475): sebagian paket yang diselamatkan dari relay grayhole adalah paket sumber
  malicious.

## Cakupan dan kegagalan

| Grup / varian | Skenario | Dievaluasi | K9_F2 memakai simulasi F2 (identik) |
|---|---|---|---|
| stage2/F2 | 27 | 27 | 0 |
| stage2/F1 | 27 | 27 | 0 |
| stage2/K9_F2 | 27 | 27 | 22 |
| ctrl0/F2 | 9 | 9 | 0 |
| ctrl0/F1 | 9 | 9 | 0 |
| ctrl0/K9_F2 | 9 | 9 | 9 |

Run gagal / berkas hilang: **0**.

## Gerbang per skenario

| Grup / varian | Determinisme A vs B | applied |
|---|---|---|
| stage2/F2 | 27/27 | 27/27 |
| stage2/F1 | 27/27 | 27/27 |
| stage2/K9_F2 | 27/27 | 27/27 |
| ctrl0/F2 | 9/9 | 9/9 |
| ctrl0/F1 | 9/9 | 9/9 |
| ctrl0/K9_F2 | 9/9 | 9/9 |

## Deteksi pada T_ids (pool skenario; label hanya evaluasi)

| Grup / varian | Sumber | TP | FP | FN | Precision | Recall | FPR |
|---|---|---|---|---|---|---|---|
| stage2/F2 | dto | 32 | 0 | 130 | 1.000 | 0.198 | 0.000 |
| stage2/F2 | bigan | 92 | 17 | 70 | 0.844 | 0.568 | 0.012 |
| stage2/F2 | isolate | 32 | 0 | 130 | 1.000 | 0.198 | 0.000 |
| stage2/F1 | dto | 32 | 0 | 130 | 1.000 | 0.198 | 0.000 |
| stage2/F1 | bigan | 92 | 17 | 70 | 0.844 | 0.568 | 0.012 |
| stage2/F1 | isolate | 106 | 17 | 56 | 0.862 | 0.654 | 0.012 |
| stage2/K9_F2 | dto | 25 | 0 | 137 | 1.000 | 0.154 | 0.000 |
| stage2/K9_F2 | bigan | 92 | 17 | 70 | 0.844 | 0.568 | 0.012 |
| stage2/K9_F2 | isolate | 25 | 0 | 137 | 1.000 | 0.154 | 0.000 |
| ctrl0/F2 | dto | 0 | 0 | 54 | – | 0.000 | 0.000 |
| ctrl0/F2 | bigan | 32 | 6 | 22 | 0.842 | 0.593 | 0.012 |
| ctrl0/F2 | isolate | 0 | 0 | 54 | – | 0.000 | 0.000 |
| ctrl0/F1 | dto | 0 | 0 | 54 | – | 0.000 | 0.000 |
| ctrl0/F1 | bigan | 32 | 6 | 22 | 0.842 | 0.593 | 0.012 |
| ctrl0/F1 | isolate | 32 | 6 | 22 | 0.842 | 0.593 | 0.012 |
| ctrl0/K9_F2 | dto | 0 | 0 | 54 | – | 0.000 | 0.000 |
| ctrl0/K9_F2 | bigan | 32 | 6 | 22 | 0.842 | 0.593 | 0.012 |
| ctrl0/K9_F2 | isolate | 0 | 0 | 54 | – | 0.000 | 0.000 |

## Jaringan, B vs A (berpasangan per skenario)

| Grup / varian | Metrik | A rata-rata | B rata-rata | B−A rata-rata | B>A / B<A / = | Wilcoxon p |
|---|---|---|---|---|---|---|
| stage2/F2 | pdr_percent | 96.732 | 98.260 | 1.5277 | 19/0/8 | 0.0001 |
| stage2/F2 | benign_pdr_percent | 97.255 | 98.398 | 1.1427 | 17/0/10 | 0.0003 |
| stage2/F2 | packet_drop_ratio_percent | 3.268 | 1.740 | -1.5277 | 0/19/8 | 0.0001 |
| stage2/F2 | grayhole_drops | 126.926 | 72.296 | -54.6296 | 0/19/8 | 0.0001 |
| stage2/F2 | throughput_kbps | 26.193 | 25.952 | -0.2403 | 4/15/8 | 0.0126 |
| stage2/F2 | latency_ms | 0.732 | 0.742 | 0.0102 | 18/1/8 | 0.0005 |
| stage2/F2 | energy_consumption_J | 54.298 | 54.294 | -0.0037 | 2/17/8 | 0.0005 |
| stage2/F1 | pdr_percent | 96.732 | 98.177 | 1.4453 | 19/2/6 | 0.0002 |
| stage2/F1 | benign_pdr_percent | 97.255 | 98.413 | 1.1572 | 17/1/9 | 0.0005 |
| stage2/F1 | packet_drop_ratio_percent | 3.268 | 1.823 | -1.4453 | 2/19/6 | 0.0002 |
| stage2/F1 | grayhole_drops | 126.926 | 73.074 | -53.8519 | 1/19/7 | 0.0001 |
| stage2/F1 | throughput_kbps | 26.193 | 24.194 | -1.9988 | 1/25/1 | 0.0000 |
| stage2/F1 | latency_ms | 0.732 | 0.776 | 0.0442 | 25/1/1 | 0.0000 |
| stage2/F1 | energy_consumption_J | 54.298 | 54.276 | -0.0218 | 0/26/1 | 0.0000 |
| stage2/K9_F2 | pdr_percent | 96.732 | 98.136 | 1.4044 | 18/0/9 | 0.0002 |
| stage2/K9_F2 | benign_pdr_percent | 97.255 | 98.257 | 1.0015 | 15/0/12 | 0.0007 |
| stage2/K9_F2 | packet_drop_ratio_percent | 3.268 | 1.864 | -1.4044 | 0/18/9 | 0.0002 |
| stage2/K9_F2 | grayhole_drops | 126.926 | 80.111 | -46.8148 | 0/18/9 | 0.0002 |
| stage2/K9_F2 | throughput_kbps | 26.193 | 25.995 | -0.1980 | 4/14/9 | 0.0386 |
| stage2/K9_F2 | latency_ms | 0.732 | 0.761 | 0.0292 | 16/2/9 | 0.0010 |
| stage2/K9_F2 | energy_consumption_J | 54.298 | 54.295 | -0.0028 | 2/16/9 | 0.0050 |
| ctrl0/F2 | pdr_percent | 99.868 | 99.868 | 0.0000 | 0/0/9 | – |
| ctrl0/F2 | benign_pdr_percent | 99.830 | 99.830 | 0.0000 | 0/0/9 | – |
| ctrl0/F2 | packet_drop_ratio_percent | 0.132 | 0.132 | 0.0000 | 0/0/9 | – |
| ctrl0/F2 | grayhole_drops | 0.000 | 0.000 | 0.0000 | 0/0/9 | – |
| ctrl0/F2 | throughput_kbps | 27.148 | 27.148 | 0.0000 | 0/0/9 | – |
| ctrl0/F2 | latency_ms | 0.686 | 0.686 | 0.0000 | 0/0/9 | – |
| ctrl0/F2 | energy_consumption_J | 54.306 | 54.306 | 0.0000 | 0/0/9 | – |
| ctrl0/F1 | pdr_percent | 99.868 | 99.855 | -0.0124 | 0/4/5 | 0.1250 |
| ctrl0/F1 | benign_pdr_percent | 99.830 | 99.828 | -0.0014 | 0/3/6 | 0.2500 |
| ctrl0/F1 | packet_drop_ratio_percent | 0.132 | 0.145 | 0.0124 | 4/0/5 | 0.1250 |
| ctrl0/F1 | grayhole_drops | 0.000 | 0.000 | 0.0000 | 0/0/9 | – |
| ctrl0/F1 | throughput_kbps | 27.148 | 24.997 | -2.1502 | 0/8/1 | 0.0078 |
| ctrl0/F1 | latency_ms | 0.686 | 0.737 | 0.0510 | 7/1/1 | 0.0156 |
| ctrl0/F1 | energy_consumption_J | 54.306 | 54.286 | -0.0201 | 1/7/1 | 0.0234 |
| ctrl0/K9_F2 | pdr_percent | 99.868 | 99.868 | 0.0000 | 0/0/9 | – |
| ctrl0/K9_F2 | benign_pdr_percent | 99.830 | 99.830 | 0.0000 | 0/0/9 | – |
| ctrl0/K9_F2 | packet_drop_ratio_percent | 0.132 | 0.132 | 0.0000 | 0/0/9 | – |
| ctrl0/K9_F2 | grayhole_drops | 0.000 | 0.000 | 0.0000 | 0/0/9 | – |
| ctrl0/K9_F2 | throughput_kbps | 27.148 | 27.148 | 0.0000 | 0/0/9 | – |
| ctrl0/K9_F2 | latency_ms | 0.686 | 0.686 | 0.0000 | 0/0/9 | – |
| ctrl0/K9_F2 | energy_consumption_J | 54.306 | 54.306 | 0.0000 | 0/0/9 | – |

## Paket sumber jujur dan isolasi (jumlah atas skenario)

| Grup / varian | paket jujur tx A → B | paket jujur rx A → B | drop grayhole A → B | node jujur diisolasi | isolasi DTO | isolasi Bi-GAN saja | drop transit isolasi | jalur gagal |
|---|---|---|---|---|---|---|---|---|
| stage2/F2 | 72925 → 72925 | 70476 → 71424 | 3427 → 1952 | 0 | 32 | 0 | 0 | 0 |
| stage2/F1 | 72925 → 72485 | 70476 → 70957 | 3427 → 1973 | 17 | 32 | 91 | 0 | 0 |
| stage2/K9_F2 | 72925 → 72925 | 70476 → 71260 | 3427 → 2163 | 0 | 25 | 0 | 0 | 0 |
| ctrl0/F2 | 24309 → 24309 | 24248 → 24248 | 0 → 0 | 0 | 0 | 0 | 0 | 0 |
| ctrl0/F1 | 24309 → 24198 | 24248 → 24137 | 0 → 0 | 6 | 0 | 38 | 0 | 0 |
| ctrl0/K9_F2 | 24309 → 24309 | 24248 → 24248 | 0 → 0 | 0 | 0 | 0 | 0 | 0 |

## Keterbatasan

- DTO memutuskan pada T_ids = 8.3 s dari observasi [0, 7.3 s). Cakupannya lebih kecil daripada DTO langkah 3 (akhir run).
- Bi-GAN memakai sampel NSL-KDD yang ditugaskan berdasarkan label skenario: bukan deteksi independen dari trafik NS-3 (K14). F1 adalah aturan fusi eksperimental yang tidak disebut paper.
- PDR gabungan mencampur efek berhentinya trafik penyerang. Untuk perlindungan trafik jujur, pakai `benign_*` (tx dan rx, bukan rasio saja).
- Energi tetap Not Available untuk DTO (K10). Flooding hanya bisa ditangkap Bi-GAN.
- Metrik waktu-dinding (`rt_compute_ms`, `computation_overhead_percent`) tidak deterministik.
- K9_F2 yang isolasi dan reroute-nya identik dengan F2 tidak disimulasikan ulang; metrik jaringannya diambil dari run F2 (identik terbukti pada pilot).
- Delegator lanjutan, alarm terdistribusi, dan reroute lanjutan belum ada (langkah 5).
