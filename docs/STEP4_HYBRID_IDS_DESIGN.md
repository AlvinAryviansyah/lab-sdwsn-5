# Langkah 4: desain integrasi Hybrid IDS (DTO + Bi-GAN) ke NS-3

Status: **DISETUJUI (K11–K18) dan DIIMPLEMENTASIKAN LOKAL; menunggu pilot server.**
Keputusan final dan penerapannya ada di **bagian 11**. Bagian 1–10 adalah usulan awal.
Bila bertentangan, bagian 11 yang berlaku (terutama K11: isolasi transit + reroute
minimal dipindah ke langkah 4).
Acuan: Kipongo et al., IEEE Access 12 (2024), Sec. III-D (hal. 3153–3156), Sec. IV-B
(hal. 3160). DTO langkah 3 dibekukan (`docs/STEP3_DTO_DESIGN.md` bagian 11).
Label: **V** = disebut paper, **U** = tidak disebut paper (keputusan kami),
**K** = perlu persetujuan.

---

## 1. Yang dikatakan paper

| Butir | Isi paper | Status |
|---|---|---|
| Struktur | "Hybrid intrusion detection ... two stages": (1) deteksi node malicious dengan DTO di secondary controller lewat investigate agent; (2) deteksi intrusi dengan Bi-GAN yang "classifies the packets as normal or malicious" | V |
| Respons DTO | "the best candidate solution is defined as the malicious node which is **isolated from the network**" | V |
| Respons Bi-GAN | Tidak ada isolasi eksplisit. "After completing the intrusion detection system, we initiate the intrusion prevention system ... an **optimal delegator is selected to notify the network about intrusions**" | V |
| Delegator | Dipilih dari "high network active time, trust, high throughput, and energy"; tanpa rumus | V (tanpa rumus) |
| Fitur Bi-GAN | Flow-based (SrcIP, DstIP, SrcPort, DstPort, ...) dan packet-based (jenis paket, respons, koneksi) | V |
| Aturan fusi DTO + Bi-GAN | Tidak disebut | U |
| Waktu deteksi, mekanisme isolasi, rerouting | Tidak disebut. Kode rilis penulis: fase pada t = 1.3 / 8.3 / 15.3 s | U |

---

## 2. Kondisi saat ini (implementasi langkah 1, dibaca dari `honeycomb-sdwsn.cc`)

Pada t = 8.3 s, `PhaseIds` melakukan hal berikut:

1. **DTO C++ (`class Dto`).** Buktinya self-report: `0.6·laju kirim + 0.4·energi`, dan
   jumlah target ditetapkan 10% node secara a priori. Fase 3 bersifat aditif. Ini bukan
   DTO langkah 3.
2. **Bi-GAN.** Prediksi dibaca dari `bigan_decisions_<n>_s<seed>.csv`. Masukannya adalah
   sampel NSL-KDD yang **ditugaskan berdasarkan label skenario**
   (`export_decisions.py`: node malicious mendapat rekaman serangan, node normal mendapat
   rekaman normal). Jadi prediksi Bi-GAN = label + galat klasifikasi NSL-KDD, bukan
   deteksi perilaku jaringan simulasi.
3. **Fusi OR.** Node diisolasi bila `bigan.pred || dtoFlag`. Keputusan hanya sekali.
4. **Isolasi = node berhenti mengirim paket miliknya sendiri** (`GenerateTraffic`).
   Node terisolasi **tetap meneruskan dan men-drop paket transit**
   (`GrayholeRouting::RouteInput` tidak memeriksa `g_blocked`). Rute tidak dihitung
   ulang. Tabel TLDQN hanya berisi satu next-hop per (node, sink), tanpa alternatif.
5. **Delegator (t = 15.3 s)** = sensor tidak terisolasi dengan sisa energi terbesar.
   Ia mengirim satu paket alarm ke sink-nya sendiri.

Garis waktu trafik sensor (dari kode): aliran mulai sekitar t = 1.4–2.4 s, 50 paket
per node, dengan interval `20/n` s (penyerang lebih cepat 1.5–5×, tetapi jumlah paket
juga dikali faktor yang sama, jadi durasinya sama). Akibatnya trafik sensor selesai
sekitar t ≈ 52 s untuk n = 20 dan t ≈ 12 s untuk n = 100. Keputusan pada 8.3 s jatuh
saat sebagian besar trafik n besar sudah terkirim.

---

## 3. Tujuan dan batas lingkup langkah 4

**Tujuan.** Mengganti sumber keputusan IDS di NS-3 dengan keputusan Python yang sudah
direproduksi, yaitu DTO langkah 3 (pra-K9) ditambah Bi-GAN. Ini dilakukan secara
**kausal**: keputusan pada waktu T hanya memakai observasi yang tersedia sebelum T.
Dampaknya diukur pada metrik jaringan dan deteksi.

**Usulan pembagian lingkup (K11):**

| Langkah 4 (ini) | Langkah 5 (berikutnya) |
|---|---|
| Keputusan Hybrid IDS dari Python, dimuat NS-3 pada T_ids | Semantik isolasi penuh: buang paket transit di node terisolasi + rerouting (tabel TLDQN kedua dengan node terisolasi di-mask) |
| Aturan fusi DTO + Bi-GAN | Delegator optimal (active time, trust, throughput, energi) dan penyebaran alarm |
| IPS **tetap** semantik langkah 1 (node berhenti mengirim), agar perubahan dapat diatribusikan | |

**Konsekuensi yang perlu diketahui sebelum menjalankan (prediksi, belum diukur).**
DTO langkah 3 hanya mendeteksi relay grayhole (bukti PLR). Flooder tidak terdeteksi
karena energi Not Available. Isolasi langkah 4 hanya menghentikan trafik milik node
sendiri, bukan drop transit. Jadi isolasi berbasis DTO diperkirakan **hampir tidak
mengubah metrik jaringan** di langkah 4. Efeknya baru terlihat setelah isolasi transit
dan rerouting (langkah 5). Bila Bi-GAN ikut mengisolasi (fusi F1), efek jaringan
didominasi Bi-GAN yang sinyalnya berasal dari label (bagian 2 butir 2). Alternatif K11:
menarik isolasi transit dan rerouting ke langkah 4.

---

## 4. Kausalitas: replay deterministik dua run

DTO butuh telemetry, sedangkan NS-3 memutuskan pada T_ids di dalam run yang sama.
Usulan (K12), sejalan dengan pola dua tahap trust di langkah 2:

1. **Run A (referensi, tanpa isolasi):** konfigurasi stage2 (rute trust telemetry),
   `--idsSource none`, `--telemWindow T_obs` dengan `T_obs = T_ids − wdLate`.
2. **Python:** DTO hanya memakai **window 0 = [0, T_obs)**. Watch di window ini selesai
   diklasifikasi paling lambat `T_obs + wdLate = T_ids`, jadi informasinya tersedia
   pada T_ids. Bi-GAN memakai prediksi yang sudah ada. Hasilnya keputusan hybrid per
   node, **tanpa kolom label**.
3. **Run B:** konfigurasi identik dengan run A, ditambah `--idsSource file`.
   Keputusan dimuat dan diterapkan pada T_ids.

**Mengapa sah.** ns-3 deterministik untuk seed dan konfigurasi yang sama, dan memuat
CSV tidak memakai RNG. Run B identik dengan run A sampai event isolasi pertama pada
T_ids, sehingga observasi yang dipakai Python sama dengan yang "dilihat" run B sebelum
T_ids. Ini **setara online**, dengan asumsi waktu komputasi DTO tidak disimulasikan
(keputusan instan; waktu nyata dicatat untuk metrik computation overhead).

**Syarat yang diuji di server (gerbang pilot):**

- telemetry window 0 run B = run A (byte-identik);
- metrik run dengan `--telemWindow T_obs` = metrik run 30 s pada konfigurasi yang sama
  (telemetry pasif);
- set node terisolasi di run B = kolom `isolate` di file keputusan.

**Parameter waktu (K12).** T_ids = 8.3 s (waktu kode rilis penulis), wdLate = 1.0 s,
jadi T_obs = 7.3 s. Perkiraan kasar, bukan hasil: bila trafik merata, bagian watch
sebelum 7.3 s sekitar 11% untuk n = 20 dan sekitar 54% untuk n = 100. Cakupan DTO
(N_j ≥ 10) akan jauh lebih kecil daripada hasil langkah 3 (yang memakai [0, 30 s) dan
seluruh run), terutama untuk n kecil. Pilot akan mengukurnya. Jumlah window telemetry
naik dari 20 menjadi 83 (ukuran `telemetry_links` naik sekitar 4×; lihat batas
memori, PAPER_DEVIATIONS 4a).

---

## 5. Komponen

### 5.1 DTO

- Metode utama: DTO langkah 3 pra-K9 (`b_max = None`), varian `main`, konfigurasi beku
  (m = 30, Y = 100, N_min = 10, δ = 0.1, α = 0.01), `windows = {0}`.
- K9 hanya sebagai pembanding di tingkat keputusan. Run NS-3 untuk K9 hanya dibuat bila
  file keputusannya berbeda dari pra-K9 (K15).
- `insufficient_evidence` → tidak ada tindakan, dilaporkan terpisah (K16).

### 5.2 Bi-GAN (tidak diubah, K14)

Prediksi `pred_intrusion` dari `bigan_decisions_*` dibaca lewat whitelist kolom
(`node_id`, `pred_intrusion`). `actual_mal` tidak dibaca oleh skrip keputusan. Tidak ada
pelatihan ulang atau pemetaan fitur (sesuai keputusan sebelumnya: menunggu tinjauan
pemetaan fitur). Pengungkapan wajib: sinyal Bi-GAN di simulasi berasal dari penugasan
sampel berdasarkan label, sehingga kinerjanya mencerminkan klasifikasi NSL-KDD, bukan
deteksi perilaku NS-3.

### 5.3 Aturan fusi (K13)

| Varian | Aturan | Dasar |
|---|---|---|
| **F2 (usulan utama)** | Isolasi bila DTO = malicious. Bi-GAN = alarm intrusi (dicatat, dilaporkan ke IPS/delegator di langkah 5), tidak mengisolasi | Paling dekat dengan teks: hanya kandidat DTO yang "isolated"; respons intrusi = notifikasi delegator |
| F1 (pembanding) | Isolasi bila DTO = malicious **atau** Bi-GAN = intrusi | Aturan langkah 1 (kontinuitas) |
| BIGAN (ekstensi proyek) | Isolasi bila prediksi Bi-GAN = intrusi; DTO hanya dievaluasi | Eksperimen opsional, bukan aturan yang dinyatakan paper |
| F3 (AND) | – | Tidak didukung paper; tidak diusulkan |

Mode `BIGAN` ditambahkan sebagai eksperimen Bi-GAN-saja (`--fusion BIGAN`). Mode ini
tidak menggantikan F2 sebagai kebijakan utama dan tidak mengubah perilaku default.

### 5.4 Format file dan perubahan C++

`hybrid_decisions_<n>_s<seed>.csv` (tanpa label):

```
node_id,dto_decision,bigan_pred,isolate,reason
```

`dto_decision` ∈ {malicious, normal, insufficient_evidence}; `reason` ∈ {dto, bigan,
dto+bigan, none}. Meta JSON berisi: SHA-256 telemetry run A, T_obs, T_ids, varian
DTO, fusi, dan konfigurasi.

Perubahan C++ (opt-in, K17):

- Opsi `--idsSource cpp|file|none` (default `cpp` = perilaku langkah 1–3, agar
  baseline tetap dapat direproduksi) dan `--idsDir`.
- `PhaseIds`:
  - `file`: `g_malicious` dan isolasi dibaca dari file (validasi header persis dan
    jumlah baris = n; fusi dilakukan di Python, bukan di C++);
  - `none`: tanpa isolasi;
  - `cpp`: tidak berubah.
- Confusion Bi-GAN tetap.
- `metrics.csv` ditambah `ids_source`.
- `class Dto`, telemetry, routing, `GrayholeRouting`, `PhasePrevention`, dan
  `PhaseMonitor` **tidak diubah**.

---

## 6. Eksperimen dan evaluasi

| Grup | Konfigurasi | Run |
|---|---|---|
| A (stage2 / ctrl0) | `--idsSource none --telemWindow 7.3`: sumber bukti dan referensi tanpa isolasi | 27 + 9 |
| B-F2 | `--idsSource file`, fusi F2, DTO pra-K9 | 27 + 9 |
| B-F1 | `--idsSource file`, fusi F1 | 27 + 9 |
| (B-K9) | Hanya bila keputusan K9 ≠ pra-K9 | ≤ 36 |
| Baseline C++ | Hasil `_stage2`/`_ctrl0` yang sudah ada (`--idsSource cpp`) | 0 (sudah ada) |
| Pilot (gerbang) | n = 20, 60, 100, seed 1: A, B-F2, dan cek passivity telemWindow | 3 × 3 |

Evaluasi (`ml/hybrid_eval.py`, satu-satunya tempat label):

- **Deteksi pada T_ids** per sumber (DTO, Bi-GAN, hybrid F1/F2): P, R, F1, FPR,
  cakupan, jumlah `insufficient_evidence`. Dibandingkan dengan DTO C++ dan dengan DTO
  langkah 3 akhir-run (untuk mengukur biaya deteksi dini).
- **Prevensi:** jumlah node terisolasi, penyerang terisolasi, node jujur terisolasi.
- **Jaringan** (berpasangan terhadap A dan terhadap baseline C++, uji Wilcoxon seperti
  langkah 2): PDR, drop ratio, drop grayhole, throughput, latency, energi, control
  overhead.
- **Target angka tidak ditetapkan.** Hasil dilaporkan apa adanya, termasuk bila sama
  dengan tanpa-IPS (prediksi bagian 3).

---

## 7. Uji

Python (`ml/tests/test_hybrid_ids.py`):

- tabel kebenaran fusi F1 dan F2;
- `insufficient_evidence` → tidak diisolasi;
- keputusan hanya dari window 0 (mutasi baris window ≥ 1 tidak mengubah keputusan);
- skrip keputusan tidak membaca `actual_mal`, `self_*`, maupun audit (pindai sumber);
- file keluaran tanpa kolom label;
- deterministik;
- DTO di dalamnya identik dengan `dto_detect` pra-K9 untuk window yang sama.

C++:

- `syntax_check.sh`;
- `--idsSource cpp` menghasilkan metrik identik dengan run langkah 2 (regresi, di
  server).

Server: gerbang pilot di bagian 4. Semua 146 uji yang ada harus tetap lolos.

---

## 8. Asumsi dan keterbatasan

1. Fusi, waktu deteksi, dan semantik isolasi tidak didefinisikan paper (U).
2. Bi-GAN berbasis sampel NSL-KDD yang ditugaskan dari label; hasil F1 tidak bisa
   ditafsirkan sebagai kemampuan deteksi perilaku.
3. DTO dini (window [0, 7.3 s)) punya cakupan lebih kecil daripada langkah 3. Hasil
   langkah 3 (akhir-run) tidak berlaku untuk T_ids.
4. Isolasi langkah 4 tidak menghentikan drop transit, jadi dampak DTO terhadap jaringan
   diperkirakan kecil (bagian 3).
5. Waktu komputasi DTO tidak disimulasikan (keputusan instan pada T_ids).
6. Keputusan sekali pada T_ids, tanpa deteksi ulang per window (sama dengan langkah 1).
7. Energi tetap Not Available (K10); flooding hanya bisa ditangkap Bi-GAN.

---

## 9. Keputusan yang perlu disetujui

| ID | Pertanyaan | Usulan |
|---|---|---|
| K11 | Lingkup langkah 4 | Integrasi keputusan saja. IPS tetap semantik langkah 1. Isolasi transit, rerouting, dan delegator → langkah 5. Alternatif: tarik isolasi transit + rerouting ke langkah 4 |
| K12 | Skema kausal dan waktu | Replay deterministik dua run; T_ids = 8.3 s, T_obs = 7.3 s (`--telemWindow 7.3`) |
| K13 | Aturan fusi | F2 utama (DTO mengisolasi; Bi-GAN = alarm); F1 pembanding |
| K14 | Bi-GAN | Dipakai apa adanya dengan pengungkapan; tanpa pelatihan ulang atau pemetaan fitur |
| K15 | DTO | Pra-K9 beku = utama; K9 hanya pembanding (run NS-3 bila keputusan berbeda) |
| K16 | `insufficient_evidence` | Tidak ada tindakan; dilaporkan terpisah |
| K17 | Kompatibilitas C++ | Opsi baru opt-in; default `cpp` mempertahankan baseline langkah 1–3 |
| K18 | Urutan kerja | Implementasi + uji lokal → pilot server (gerbang bagian 4) → sweep penuh |

---

## 10. Rencana implementasi (setelah disetujui)

| Berkas | Isi |
|---|---|
| `ml/hybrid_ids.py` | Keputusan hybrid dari telemetry run A (window 0) + Bi-GAN (whitelist kolom); keluaran CSV + meta |
| `ml/hybrid_eval.py` | Evaluasi deteksi, prevensi, dan jaringan (label hanya di sini) |
| `ml/telemetry_schema.py` | Whitelist `BIGAN_INPUT_COLUMNS = ["node_id", "pred_intrusion"]` |
| `ml/tests/test_hybrid_ids.py` | Uji bagian 7 |
| `ns3-sim/honeycomb-sdwsn.cc` | `--idsSource`, `--idsDir`, loader `HybridDecisions`, cabang di `PhaseIds`, kolom `ids_source` |
| `ns3-sim/BUILD.md` | Command run A/B dan pilot |
| `docs/PAPER_DEVIATIONS.md` §2f, README | Setelah ada hasil |

Yang tidak diubah: TLDQN, Bi-GAN (model dan keputusan), DTO langkah 3 (beku),
telemetry, routing, `GrayholeRouting`, delegator.

---

## 11. Keputusan yang disetujui dan implementasi

### 11.1 Keputusan

| ID | Keputusan reviewer | Penerapan |
|---|---|---|
| K11 | Langkah 4 = integrasi keputusan + isolasi (trafik asal **dan** penerusan transit) + reroute deterministik minimal. Delegator lanjutan, alarm terdistribusi, dan reroute lanjutan → langkah 5. Jalur tidak boleh direka; bila tidak ada alternatif, kegagalan rute dilaporkan eksplisit | `IsolationGate` (C++) membuang transit di node terisolasi; `ApplyReroute` (C++) memasang tabel dari `hybrid_ids.reroute` (Python); kegagalan → `failed_entries`, `paths[].status = failed`, `reroute_unresolved` |
| K12 | T_obs = 7.3 s, T_ids = 8.3 s, dua run. Sebelum eksperimen penuh, A dan B harus byte-identik sampai isolasi pertama; bila gagal: berhenti dan investigasi | `--telemWindow=7.3`; `hybrid_ids.py` menolak telemetry dengan `window_s ≠ T_obs` atau `T_obs + wdLate > T_ids`; gerbang `hybrid_eval.py determinism` |
| K13 | F2 utama (DTO mengisolasi, Bi-GAN alarm saja); F1 pembanding, **eksperimental, tidak disebut paper** | `--fusion F2|F1`; dicatat di `hybrid_meta.json` (`fusion_note`) |
| K14 | Bi-GAN apa adanya, tanpa pelatihan ulang. Pengungkapan: keputusan Bi-GAN di simulasi berasal dari rekaman NSL-KDD yang ditugaskan berdasarkan label skenario, jadi **bukan deteksi independen dari trafik NS-3**. Langkah ini **tidak** menyelesaikan ketidakcocokan skema fitur maupun kebocoran label | Hanya `node_id, pred_intrusion` dibaca (`BIGAN_INPUT_COLUMNS`); `bigan_note` di meta |
| K15 | Pra-K9 utama; K9 pembanding; keduanya dibandingkan pada skenario dan window yang sama di pilot; konfigurasi utama tidak diganti diam-diam | `--b-max 0` (default `hybrid_ids.py`) = pra-K9; `--b-max 0.8` = K9; metode tercatat di `hybrid_meta.json` |
| K16 | `insufficient_evidence` = tidak ada tindakan; bukan normal maupun malicious | `fuse()`; evaluasi melaporkannya terpisah (`dto_insufficient_evidence`). Di confusion C++ `dto_*` dihitung sebagai "tidak ditandai" |
| K17 | `--idsSource=cpp|file|none`, default `cpp`; DTO C++, telemetry, routing, dan delegator tidak berubah kecuali diperlukan integrasi; default harus mereproduksi baseline | Lihat 11.2; gerbang P0 di `ns3-sim/BUILD.md` 4c |
| K18 | Lokal → uji → pilot server → determinisme dua run → evaluasi pilot dan review → sweep penuh hanya setelah persetujuan eksplisit | Status saat ini: tahap 1–2 selesai |

### 11.2 Perubahan C++ (`honeycomb-sdwsn.cc`)

| Komponen | Mode `cpp` (default) | Mode `none` | Mode `file` |
|---|---|---|---|
| DTO C++ + fusi OR + isolasi trafik asal | **tidak berubah** | tidak dijalankan | tidak dijalankan |
| `IsolationGate` (prioritas 200, di atas grayhole) | tidak dipasang | dipasang, tidak pernah aktif | dipasang; aktif untuk node terisolasi setelah 8.3 s |
| Keputusan IDS | `class Dto` | tidak ada | `hybrid_decisions_<n>_s<seed>.csv` (header persis, tanpa label) |
| Reroute | – | – | `reroute_nexthop_<n>_s<seed>.csv`; hanya entri yang next-hop-nya berubah yang diganti |
| Snapshot `ids_snapshot_<n>_s<seed>.csv` pada T_ids (sebelum tindakan) | tidak ditulis | ditulis | ditulis |
| Baris metrik baru (`ids_mode`, `isolation_transit_drops`, `isolated_by_dto`, `isolated_by_bigan_only`, `bigan_alarms`, `reroute_changed`, `reroute_unresolved`) | tidak ditulis | ditulis | ditulis |

Tidak berubah: `class Dto`, `GrayholeRouting`, telemetry (`namespace telem`), pemasangan
rute awal, `PhasePrevention` (delegator), `PhaseMonitor`, TLDQN, dan Bi-GAN.

Catatan implementasi (keputusan kami, U):

1. **Gerbang dipasang juga di mode `none`.** Tujuannya agar tumpukan routing run A dan
   run B identik. Gerbang tidak memakai RNG atau event dan selalu mengembalikan
   `false` sampai ada isolasi.
2. **Isi snapshot:** waktu, `Simulator::GetEventCount()`, counter grayhole, pesan
   kontrol, counter IP UDP (penerusan, penerusan terkirim, asal, lokal), paket kirim
   per sensor, dan sisa energi per sensor (17 digit).
3. **Kolom telemetry yang melihat ke depan.** `wd_heard_after_timeout`
   (`obs_heard_after_timeout`) menghitung frame yang terdengar setelah wdLate, yang
   bisa terjadi setelah T_ids. Karena itu kolom ini boleh berbeda antara A dan B di
   window 0. Gerbang memeriksa kolom masukan DTO; perbedaan kolom lain dilaporkan.
4. **Kegagalan rute.** Entri tanpa kandidat sah dibiarkan menunjuk node terisolasi.
   Paketnya dibuang di node itu dan tercatat di `isolation_transit_drops`. Tidak ada
   jalur rekaan.
5. **Delegator (langkah 5) tidak diubah.** Ia tetap memilih sensor tidak terisolasi
   dengan energi terbesar, dan sekarang himpunan terisolasinya berasal dari keputusan
   file.
6. **`reroute_unresolved` (metrik C++)** hanya menghitung entri yang next-hop-nya
   langsung node terisolasi. Entri yang buntu lebih jauh di hilir tidak terhitung.
   Acuan kegagalan rute adalah `hybrid_meta.json` (`failed_entries`, `paths[].status`).
7. **Batas gerbang determinisme.** A dan B sama-sama memasang `IsolationGate`, jadi
   gerbang tidak membuktikan `none` = `cpp` sebelum 8.3 s. Kepasifan gerbang terhadap
   baseline hanya didukung oleh argumen kode: tanpa RNG, tanpa event, selalu `false`
   sebelum isolasi, dan `SetIpv4` kosong. Mode `cpp` tidak menulis snapshot.
8. **Snapshot** membuat folder `telemDir` sendiri, jadi tetap berfungsi dengan
   `--telemetry=false`.

### 11.3 Reroute minimal (`ml/hybrid_ids.py`)

- Q-value dihitung dari observasi yang sama dengan ekspor tabel awal (model, trust, dan
  tabel diverifikasi dengan SHA-256 terhadap `tldqn_nexthop_meta.json`). **Tanpa isolasi,
  hasilnya identik dengan tabel awal** pada 54 skenario (`routes_stage2` dan
  `routes_stage1`).
- Untuk setiap (c, t) dengan c tidak terisolasi, dipilih argmax Q atas kandidat honeycomb
  yang bukan node terisolasi dan bukan node buntu untuk t. Pasangan diproses urut jarak
  ke t naik. Kandidat selalu lebih dekat ke t, jadi node buntu ditetapkan sebelum
  dipakai dan hasilnya bebas loop. Entri yang argmax-nya tidak terkena tetap sama
  (minimal).
- **Pemangkasan node buntu** (kandidat yang semua jalurnya menuju node terisolasi tidak
  dipilih) adalah keputusan kami (U). Ia hanya memakai kandidat TLDQN yang sudah ada.
- Observasi TLDQN tidak diubah (fitur `valid` kandidat terisolasi tetap 1). Isolasi hanya
  diterapkan sebagai mask aksi, agar entri lain tidak berubah.
- Keluaran per skenario (`hybrid_meta.json`): entri yang diganti, entri gagal, dan status
  jalur setiap sumber tidak terisolasi (`ok` / `failed` + node pemblokir).

### 11.4 Uji (lokal)

`ml/tests/test_hybrid_ids.py` (21 uji; total repo **167 lolos**):

- berkas keputusan ditulis LF dan header-nya byte-identik dengan pembanding di loader
  C++ (ditambahkan setelah review: versi awal menulis CRLF, sehingga semua run `file`
  akan berhenti dengan fatal error);

- tabel kebenaran fusi F1/F2;
- `insufficient_evidence` tidak pernah memicu isolasi oleh DTO;
- F2 mengisolasi DTO saja, F1 menambah Bi-GAN;
- hanya window observasi yang dipakai;
- DTO identik dengan detektor langkah 3 beku;
- K9 hanya opt-in;
- deterministik;
- sumber tanpa label;
- loader Bi-GAN mengabaikan kolom label;
- kontrak header dengan C++;
- reroute:
  - tanpa isolasi mereproduksi tabel;
  - relay terisolasi dihindari hanya dengan kandidat TLDQN, dan entri lain tetap;
  - tanpa alternatif → kegagalan eksplisit dan entri dibiarkan;
- gerbang determinisme:
  - identik → lulus;
  - snapshot berbeda → gagal;
  - masukan DTO window 0 berbeda → gagal;
  - window lain atau kolom yang melihat ke depan → dilaporkan, tidak gagal.

C++: `ns3-sim/tools/syntax_check.sh` lolos terhadap header ns-3.48. Regresi default dan
determinisme dua run hanya bisa diverifikasi di server (`ns3-sim/BUILD.md` 4c).

### 11.5 Prediksi yang perlu diuji pilot (belum diukur)

- Cakupan DTO pada [0, 7.3 s) jauh lebih kecil daripada langkah 3. Contoh dari dry run
  kode pada telemetry 30 s **bukan hasil**; pilot akan mengukur cakupan dengan window
  7.3 s.
- Dengan isolasi transit, relay grayhole yang terdeteksi DTO berhenti men-drop dan
  tetangganya di-reroute. Efek jaringan kini mungkin, tetapi dibatasi oleh cakupan dini
  dan oleh trafik n besar yang sudah selesai sekitar t ≈ 12 s.
- Pada F1, isolasi didominasi Bi-GAN (sinyal turunan label, K14). Node jujur yang
  salah diisolasi (FP Bi-GAN) bisa memutus jalur tetangga bila tidak ada alternatif.

### 11.6 Pilot percobaan 1 (commit server `c757ba5`): TIDAK SAH sebagai gerbang langkah 4

- **Penyebab.** Commit implementasi langkah 4 (`92f4cfb`) belum ada di remote saat
  server melakukan `git pull`. Server membangun kode langkah 3 (`7f25685`).
- **P1 (run A) gagal.** `--idsSource=none` tidak dikenal oleh binary lama, sehingga ns-3
  mencetak bantuan dan keluar dengan status 1 (`log_20_s1_s4A.txt`). Tidak ada data run A.
- **P0 berjalan dengan binary lama.** Hasilnya **bukan** bukti untuk kode langkah 4. Yang
  terukur (lingkungan server, binary lama, n = 20/60/100 seed 1):
  - telemetry (`telemetry_links_*`) dan `timeseries_*` identik byte dengan `step2/*_stage2`;
  - `metrics_*` identik untuk semua baris **kecuali** `rt_compute_ms` dan
    `computation_overhead_percent`; begitu pula `_s4tw` (`--telemWindow=7.3`) terhadap
    `_stage2`.
- **Koreksi gerbang.** Kedua baris itu adalah metrik waktu-dinding (pengukuran 3D Cube
  dengan `std::chrono`), sehingga berbeda di setiap run walau simulasi identik. Gerbang
  P0 versi awal ("metrics identik byte") karenanya tidak mungkin lolos. Gerbang sekarang
  memakai `hybrid_eval.py identical --metrics`: semua baris harus identik kecuali dua
  baris waktu-dinding, yang nilainya tetap dilaporkan. Baris tambahan atau urutan baris
  yang berbeda tetap dianggap gagal.
- **Pencegahan.** BUILD.md 4c P0 kini memeriksa bahwa sumber di `scratch/` dan binary
  memuat `--idsSource` sebelum run apa pun.
- Berkas hasil `c757ba5` dipindah (`git mv`) ke
  `ns3-sim/results/step4/attempt1_oldbinary/` beserta `NOTE.md`, agar tidak tertimpa
  saat P0/P1 dijalankan ulang dengan binary langkah 4.

### 11.7 Pilot percobaan 2 (binary `9928d98`, n = 20/60/100, seed 1): hasil terukur

> **HASIL PILOT PRELIMINER: 3 skenario, 1 seed.** Ini bukan hasil akhir langkah 4 dan
> belum menjadi dasar kesimpulan. Metrik PDR khusus sumber jujur belum ada pada binary
> ini (lihat keterbatasan butir 1 dan pilot ulang 11.8).

Data: `ns3-sim/results/step4/` (run A `_s4A`; run B `_s4B_{F2,F1,K9_F2}`; P0 `_s4reg`,
`_s4tw`). Laporan: `ml/reports/step4_pilot_determinism_*.json`,
`ml/reports/step4_pilot_eval_{F2,F1}.json`. Percobaan gagal sebelumnya ada di
`attempt1_oldbinary/` (binary lama) dan `attempt_p2a_nodecisions/` (`dec_*` belum
di-push, tidak ada data).

**Gerbang (semua LULUS):**

| Gerbang | Hasil |
|---|---|
| P0 regresi default `cpp` vs `step2/*_stage2` | metrik identik kecuali 2 baris waktu-dinding; `timeseries`, `telemetry`, `telemetry_links`, `watchdog_audit` identik byte (3/3) |
| P0 passivity `--telemWindow=7.3` | metrik identik kecuali 2 baris waktu-dinding (3/3) |
| Kepasifan gerbang isolasi sebelum T_ids | window 0 `cpp` (tanpa gerbang, `_s4tw`) = `none` (`_s4A`) di **semua** kolom node dan links (3/3). Ini menutup batas 11.2 butir 7 |
| Ulang server | dua run berurutan binary yang sama (`1ffe722` → `d4daf8e`): hanya baris waktu-dinding yang berubah |
| K12 determinisme A vs B | **LULUS 9/9** (F2, F1, K9_F2 × 3): snapshot T_ids = 8.3 s identik byte; window 0 identik di semua kolom, tidak hanya masukan DTO |
| Penerapan keputusan | jumlah isolasi, isolasi DTO / Bi-GAN saja, alarm, dan reroute di metrik C++ = berkas Python (9/9) |
| `file` tanpa isolasi = `none` | F2 n=20 (0 isolasi): telemetry identik byte; metrik hanya berbeda di counter keputusan (`ids_mode`, `dto_*`, `bigan_alarms`) |
| K9_F2 vs F2 | isolasi dan reroute identik → metrik (kecuali waktu-dinding) dan telemetry identik (3/3) |

**Deteksi pada T_ids (window [0, 7.3 s); pool 3 skenario, 18 malicious; label hanya
evaluasi):**

| Sumber | TP | FP | FN | P | R |
|---|---|---|---|---|---|
| DTO pra-K9 | 4 | 0 | 14 | 1.000 | 0.222 |
| Bi-GAN (sinyal turunan label, K14) | 9 | 4 | 9 | 0.692 | 0.500 |
| Isolasi F2 | 4 | 0 | 14 | 1.000 | 0.222 |
| Isolasi F1 (eksperimental) | 10 | 4 | 8 | 0.714 | 0.556 |

- Cakupan DTO dini hanya 4/18 malicious, dengan 115 node `insufficient_evidence`.
  Semua malicious yang punya bukti terdeteksi, dan tidak ada FP.
- F1 mengisolasi 4 node jujur (FP Bi-GAN). F2 mengisolasi 0 node jujur.
- K9 vs pra-K9: berbeda hanya di n=100 (2 node normal → `insufficient_evidence`), tanpa
  efek pada isolasi.
- Jalur gagal setelah reroute: 0. Satu entri F1 n=20 tanpa alternatif tidak dipakai
  sumber aktif mana pun. `isolation_transit_drops` = 0 di semua run: reroute
  memindahkan transit sebelum sampai di node terisolasi.

**Jaringan, B vs A (per skenario; 3 pasangan, tanpa uji statistik):**

| Varian | n | PDR % (A → B) | drop % | drop grayhole | throughput kbps | latency ms | energi J |
|---|---|---|---|---|---|---|---|
| F2 | 20 | 100.00 → 100.00 | 0 → 0 | 0 → 0 | 7.325 → 7.325 | 0.2876 → 0.2876 | 18.044 → 18.044 |
| F2 | 60 | 99.06 → 99.60 | 0.94 → 0.40 | 33 → 14 | 29.57 → 29.59 | 0.4079 → 0.4123 | 54.315 → 54.314 |
| F2 | 100 | 96.22 → 97.45 | 3.78 → 2.55 | 223 → 147 | 39.08 → 38.81 | 0.4373 → 0.4448 | 90.569 → 90.563 |
| F1 | 20 | 100.00 → 100.00 | 0 → 0 | 0 → 0 | 7.325 → 7.059 | 0.2876 → 0.3135 | 18.044 → 18.043 |
| F1 | 60 | 99.06 → 99.55 | 0.94 → 0.45 | 33 → 14 | 29.57 → 26.07 | 0.4079 → 0.4154 | 54.315 → 54.278 |
| F1 | 100 | 96.22 → 97.39 | 3.78 → 2.61 | 223 → 147 | 39.08 → 37.98 | 0.4373 → 0.4520 | 90.569 → 90.554 |

**Keterbatasan tafsiran (penting sebelum sweep penuh):**

1. **PDR dan throughput gabungan mencampur dua efek.** Node terisolasi berhenti
   mengirim trafik miliknya sendiri, sehingga penyebut PDR mengecil (n=100 F2: paket UDP
   terkirim 5905 → 5759). Pada saat yang sama drop grayhole turun (223 → 147). Metrik
   saat ini tidak punya PDR khusus sumber jujur, jadi kenaikan PDR **tidak bisa**
   diatribusikan ke perlindungan trafik jujur.
2. Penurunan throughput pada F1 sebagian besar karena trafik node jujur yang salah
   diisolasi (FP Bi-GAN) ikut berhenti.
3. Latency naik sedikit (reroute ke jalur lain).
4. Tiga skenario, satu seed: indikasi awal, bukan kesimpulan.

### 11.8 PDR khusus sumber jujur dan pilot ulang r2 (disetujui; hasil belum ada)

**Definisi** (`BenignDelivery` di `honeycomb-sdwsn.cc`, evaluasi pasca-simulasi):

- Aliran = FlowStats FlowMonitor UDP, yaitu himpunan yang sama dengan `pdr_percent`
  (TCP user tetap dikecualikan). Sebuah aliran dihitung bila alamat sumbernya adalah
  sensor (`g_ipToSensor`) dengan ground truth bukan malicious. Ini klasifikasi yang
  sama dengan `benign_hops_per_rx_est` yang sudah ada.
- `benign_tx_packets` = Σ txPackets; `benign_rx_packets` = Σ rxPackets;
  `benign_pdr_percent` = rx / tx × 100. Bila `benign_tx_packets = 0`, nilainya
  `benign_pdr_percent = nan` dan `benign_pdr_defined = 0` (**tidak** dilaporkan 100%).
  `hybrid_eval.py` tidak memasangkan nilai `nan` dan memeriksa bahwa nilai tertulis =
  rx / tx.
- Aliran alarm delegator ikut dihitung bila delegatornya sensor jujur, sama seperti
  pada `pdr_percent`.
- Label dipakai **hanya** di blok metrik setelah `Simulator::Run()` (diuji di sumber).
  Label tidak menjadi masukan DTO, Bi-GAN, fusi, isolasi, maupun routing.
- Baris hanya ditulis pada mode `file`/`none`. Mode `cpp` tetap tanpa baris baru
  (diuji di sumber; diverifikasi di server lewat gerbang P0 r2).

**Uji baru:**

- struktur C++ asli dikompilasi dan diuji: klasifikasi (malicious dan non-sensor
  dibuang), agregasi, PDR, dan tx = 0 → NaN;
- definisi Python;
- baris hanya di blok non-cpp dan setelah `Simulator::Run`;
- pemeriksa konsistensi `evaluate`;
- gerbang pilot dari data tersimpan (`applied`, `same-inputs`, `determinism`).

Total **176 uji lolos**.

**Pilot ulang r2** (`ns3-sim/BUILD.md` 4c, tag `_s4r2*`, hasil ke
`ns3-sim/results/step4/r2/`). Hasil pilot sebelumnya tidak ditimpa. Gerbang:

1. P0 r2: default `cpp` vs `step2` (metrik kecuali waktu-dinding; timeseries dan
   telemetry identik byte) dan passivity `--telemWindow`;
2. `same-inputs`: telemetry run A r2 = telemetry yang menjadi dasar `dec_*`
   (SHA-256), sehingga keputusan yang ada tetap sah;
3. determinisme A vs B r2 untuk 9 kombinasi;
4. `applied`: isolasi, alarm, dan reroute di C++ = berkas Python;
5. evaluasi: PDR gabungan vs PDR sumber jujur, F2 / F1 / K9_F2 (definisi tidak berubah).

Sweep penuh tetap menunggu persetujuan eksplisit setelah laporan r2.

### 11.9 Pilot ulang r2 (binary `826ff22`, n = 20/60/100, seed 1): hasil terukur

> **HASIL PILOT PRELIMINER: 3 skenario, 1 seed.** Bukan hasil akhir langkah 4.

Data: `ns3-sim/results/step4/r2/` (server commit `f59a8e0`). Laporan:
`ml/reports/step4_r2_{same_inputs,determinism,applied,eval}_{F2,F1,K9_F2}.json`.

**Gerbang (semua LULUS):**

| Gerbang | Hasil |
|---|---|
| Binary r2 | `none`/`file` menulis 5 baris `benign_*` baru. `cpp` hanya memuat baris lama `benign_hops_per_rx_est` |
| P0 regresi `cpp` vs `step2` | himpunan dan urutan baris metrik sama; nilai identik kecuali 2 baris waktu-dinding; `timeseries`, `telemetry`, `telemetry_links`, `watchdog_audit` identik byte (3/3) |
| P0 passivity `--telemWindow=7.3` | identik kecuali 2 baris waktu-dinding (3/3) |
| `same-inputs` | telemetry run A r2 = dasar `dec_*` (SHA-256). Run A r2 juga identik byte dengan run A pilot 2 (telemetry, links, snapshot) |
| Determinisme A vs B | **9/9**: snapshot T_ids identik byte; window 0 identik di semua kolom |
| `applied` | isolasi, alarm, dan reroute di C++ = berkas Python (9/9) |
| r2 B vs pilot-2 B | hanya 5 baris baru yang bertambah; metrik lama (kecuali waktu-dinding) dan telemetry identik (9/9). Metrik baru tidak mengubah simulasi |

**PDR gabungan vs PDR sumber jujur, B vs A:**

| Varian | n | PDR gabungan % | PDR jujur % | paket jujur tx | paket jujur rx | drop grayhole |
|---|---|---|---|---|---|---|
| F2 | 20 | 100.00 → 100.00 | 100.00 → 100.00 | 901 → 901 | 901 → 901 | 0 → 0 |
| F2 | 60 | 99.06 → 99.60 | 98.78 → 99.48 | 2701 → 2701 | 2668 → 2687 | 33 → 14 |
| F2 | 100 | 96.22 → 97.45 | 95.05 → 96.73 | 4501 → 4501 | 4278 → 4354 | 223 → 147 |
| F1 | 20 | 100.00 → 100.00 | 100.00 → 100.00 | 901 → 901 | 901 → 901 | 0 → 0 |
| F1 | 60 | 99.06 → 99.55 | 98.78 → 99.48 | 2701 → 2701 | 2668 → 2687 | 33 → 14 |
| F1 | 100 | 96.22 → 97.39 | 95.05 → 96.69 | 4501 → 4436 | 4278 → 4289 | 223 → 147 |
| K9_F2 | semua | identik dengan F2 | identik dengan F2 | | | |

Rata-rata berpasangan B − A (3 skenario): F2 PDR gabungan +0.585 pp, PDR jujur
+0.797 pp; F1 +0.552 dan +0.781 pp.

**Temuan (terukur, preliminer):**

1. **F2 melindungi trafik jujur.** Paket jujur terkirim tidak berubah, karena tidak ada
   node jujur yang diisolasi. Kenaikan paket jujur yang diterima (+19 di n=60, +76 di
   n=100) **sama persis** dengan penurunan drop grayhole (33 → 14, 223 → 147). Seluruh
   paket yang diselamatkan dari relay grayhole adalah paket sumber jujur.
2. **PDR gabungan meremehkan efek F2** (+0.585 vs +0.797 pp), karena trafik flooding
   penyerang yang diisolasi ikut keluar dari penyebut.
3. **F1 mengorbankan trafik jujur.** Di n=100, 65 paket jujur tidak pernah dikirim
   karena node jujur salah diisolasi (FP Bi-GAN). Paket jujur yang diterima hanya naik
   +11, dibanding +76 pada F2. Rasio PDR jujurnya hampir sama dengan F2 (96.69 vs
   96.73), tetapi jumlah paket jujur yang sampai lebih sedikit. **Rasio PDR saja tidak
   cukup untuk membandingkan F1 dengan F2.** `benign_rx_packets` dan
   `benign_tx_packets` perlu dilaporkan bersamanya.
4. n=20: tidak ada efek (F2 tidak mengisolasi; F1 mengisolasi 1 penyerang). Throughput F1
   turun karena flooding penyerang berhenti.
5. Tiga skenario, satu seed, tanpa uji statistik: indikasi awal. Sweep penuh menunggu
   persetujuan.

### 11.10 Sweep penuh (disetujui): rencana

- Skenario: stage2 (`routes_stage2`) n = 20…100 × seed 1–3 = 27, ditambah ctrl0
  (`routes_stage1`, `--grayholeDrop=0`, seperti langkah 2) n = 20/60/100 × seed 1–3 = 9.
- Run A: `--idsSource=none --telemWindow=7.3` (36 run). Run B: F2 dan F1 untuk semua 36
  skenario. K9_F2: keputusan dibuat untuk semua skenario, tetapi simulasinya **hanya**
  dijalankan bila kolom `isolate` atau tabel reroute berbeda dari F2. Bila keduanya
  identik, simulasi K9_F2 sama dengan F2 (terbukti 3/3 pada pilot) dan dilaporkan
  sebagai "identik dengan F2".
- Runner `ns3-sim/run_step4_list.sh` mencatat status setiap run dan tidak berhenti saat
  ada kegagalan. Kegagalan dilaporkan eksplisit.
- Gerbang per skenario: determinisme A vs B dan `applied`. Definisi DTO, fusi, Bi-GAN,
  dan reroute tidak berubah.

### 11.11 Sweep penuh: hasil

Laporan gabungan: **`docs/STEP4_RESULTS.md`** (ringkasan + tabel). Data:
`ns3-sim/results/step4/full/`. JSON: `ml/reports/step4_full_report.json`.

113 run NS-3 (36 A + 77 B), 0 gagal. Determinisme dan `applied` lulus 108/108. Dataset
run B resmi adalah pass pertama `c02ac4f`; pass kedua yang tumpang-tindih tidak dipakai
(lihat ringkasan laporan).

**Koreksi 11.9 butir 1.** Kesamaan "paket jujur diselamatkan = drop grayhole
dihindari" hanya berlaku pada 3 skenario pilot. Pada sweep penuh, F2 stage2 memberi +948
paket jujur dan −1475 drop grayhole: sebagian drop yang dihindari adalah paket sumber
malicious.
