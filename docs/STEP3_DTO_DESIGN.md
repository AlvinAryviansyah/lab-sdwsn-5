# Langkah 3: desain DTO (Driver Training-based Optimization) di atas telemetry NS-3

Status: **DITERIMA DAN DIBEKUKAN** sebagai bagian reproduksi. Metode utama = **pra-K9**
(`--b-max 0`); K9 (b_max = 0.8) = varian pembanding eksperimental; N(1 − b) ditunda.
Keputusan final, konfigurasi, dan command ada di **bagian 11**. Bagian 1–10 adalah
riwayat desain dan eksperimen, dipertahankan apa adanya (termasuk hasil negatif).
Acuan: Kipongo et al., IEEE Access 12 (2024), Sec. III-D-1, pers. (21)–(31), Algoritma 2.
TLDQN dan Bi-GAN tidak diubah. Simulasi C++ juga tidak diubah di langkah ini (DTO
berjalan offline di Python di atas telemetry yang sudah tervalidasi; lihat bagian 6).

Label: **V** = disebut paper, **U** = tidak disebut paper (keputusan kami),
**K** = keputusan yang perlu disetujui reviewer (bagian 9).

---

## 1. Metodologi DTO menurut paper

### 1.1 Peran di sistem

- DTO adalah tahap pertama hybrid IDS: **deteksi node malicious**. Tahap kedua,
  Bi-GAN, mengklasifikasi paket (Sec. III-D, Fig. 2). (V)
- Pelaksananya **secondary controller** dengan bantuan **investigate agent** di
  edge server. Agent ini "monitors and records the behaviors of the sensor nodes". (V)
- Masukan: "investigated information", dengan kriteria **energy consumption,
  packet delivery ratio, dan packet loss ratio**. (V)
- Keluaran: "malicious node detection". Paper menyatakan "the best candidate
  solution is defined as the malicious node which is isolated from the network". (V)
- Hasil yang dilaporkan: "the number of illegitimate sensor nodes identified is 10%
  with respect to number of nodes" (Sec. IV-D-1). Itu sama dengan proporsi node
  ilegitimat di skenario. (V)
- Perilaku yang ingin ditangkap (Sec. IV-C-1): "abnormal power consumption, unusual
  data transmission patterns, or deviation from expected node behavior". (V)

### 1.2 Yang **tidak** didefinisikan paper

| Butir | Status |
|---|---|
| Rumus fungsi objektif OF dari ketiga kriteria (bobot, normalisasi, arah) | tidak ada |
| Arti variabel keputusan z (apa yang dikodekan satu kandidat solusi) | tidak ada |
| Cara mendeteksi **lebih dari satu** node malicious (paper hanya menyebut "best candidate solution") | tidak ada |
| Aturan berhenti / ambang keputusan | tidak ada |
| Ukuran populasi m, jumlah iterasi Y, batas BL/BU | tidak ada |
| Waktu dan frekuensi eksekusi DTO selama 600 s | tidak ada |
| Cara investigate agent memperoleh energi/PDR/loss per node | tidak ada |

Konsekuensinya, tanpa asumsi tambahan DTO di paper tidak bisa diimplementasikan.
Semua asumsi tambahan di bawah diberi label **U** atau **K**.

---

## 2. Penjelasan persamaan (21)–(31)

Notasi. Paper memakai `n` untuk dua hal sekaligus: ukuran populasi (`Z` berukuran
"n×1") dan jumlah variabel (matriks "m×n", `j = 1..n`). Di dokumen ini:
`m` = ukuran populasi, `d` = jumlah variabel, `q` = iterasi ke-q, `Y` = iterasi maksimum.

| Pers. | Isi | Arti |
|---|---|---|
| (21) | `Z = [Z_1 … Z_m]ᵀ`, `Z_i = (z_i1 … z_id)` | Populasi m "learner driver"; tiap baris = satu kandidat solusi dengan d variabel |
| (22) | `z_ij = BL_j + Rand·(BU_j − BL_j)` | Inisialisasi acak dalam batas. Paper menulis `Rand ∈ [0, 2]`, yang bisa melampaui `BU_j`; lihat K6 |
| (23) | `OF = [OF_1 … OF_m]ᵀ` | Nilai objektif tiap kandidat. Algoritma **meminimalkan** OF (seleksi greedy memakai `<`) |
| (24) | `ID` = matriks `nID × d` driving instructor; `nID = ⌊0.1·m·(1 − q/Y)⌋` | Instruktur = `nID` anggota terbaik menurut OF ("Determine ID based on the value of objective function"). Jumlahnya menyusut linear terhadap iterasi; di q = Y nilainya 0, sehingga dibutuhkan batas bawah 1 (U) |
| (25) | Fase 1 (pelatihan oleh instruktur): jika `OF_ID_k < OF_i`: `z^P1 = z + Rand·(ID_k − Rand1·z)`; selain itu: `z^P1 = z + Rand·(z − ID_k)` | Bergerak **mendekati** instruktur acak `k ∈ {1..nID}` bila instruktur lebih baik, **menjauh** bila lebih buruk. `Rand ∈ [0,1]`, `Rand1 ∈ [1,2]` |
| (26) | `Z_i ← Z^P1` jika `OF^P1 < OF_i` | Penerimaan greedy |
| (27) | Fase 2 (meniru pola instruktur): `z^P2 = P·z + (1−P)·ID_k` | Kombinasi cembung posisi sendiri dan instruktur |
| (28) | Penerimaan greedy fase 2 | – |
| (29) | `P = 0.01 + 0.9·(1 − q/Y)` | Bobot posisi sendiri turun dari 0.91 ke 0.01, sehingga makin akhir makin meniru instruktur |
| (30) | Fase 3 (latihan pribadi, pencarian lokal): `z^P3 = z + (1 − 2·Rand)·(1 − q/Y)·z` | Perturbasi acak **sebanding dengan z sendiri**, dengan amplitudo menyusut ke 0 di akhir. Bersifat multiplikatif: bila z dekat 0, langkahnya juga dekat 0 |
| (31) | Penerimaan greedy fase 3 | – |

Algoritma 2: untuk `q = 1..Y`, untuk tiap anggota `i`, jalankan fase 1 → 2 → 3
berurutan, masing-masing dengan penerimaan greedy. Di akhir tiap iterasi, perbarui
solusi terbaik.

Rujukan [55] yang dikutip paper untuk "current position" (25) adalah paper lokalisasi
NLOS di VANET, bukan sumber algoritma DTO. Kami **mengikuti persamaan yang tertulis di
paper ini** dan tidak memakai versi lain.

---

## 3. Masukan dan keluaran: tafsiran kami

### 3.1 Implementasi saat ini (C++ `class Dto`, dibuat langkah 1) dan masalahnya

| Butir | Saat ini | Masalah |
|---|---|---|
| Kandidat solusi | Satu anggota populasi = satu node, dengan `OF_i = (z_i − bukti_i)²` | Tiap anggota punya objektif **berbeda**, sehingga perbandingan dengan instruktur (25) tidak bermakna. Optimumnya trivial (`z_i = bukti_i`), jadi DTO hanya menyalin bukti |
| Bukti | `0.6·laju kirim + 0.4·energi` milik node | Keduanya **self-report** (setara `self_*`), dan tidak memakai PDR/loss sama sekali |
| Jumlah terdeteksi | top-k dengan k = 10% node | k = jumlah penyerang sebenarnya, diberikan **a priori** (kebocoran informasi skenario) |
| Fase 3 | aditif `±0.5·(1−q/Y)` | bukan pers. (30) |
| Waktu | t = 8.3 s, sekali | – |

Kode ini tidak diubah di langkah 3. Ia dipakai sebagai **pembanding baseline**
(`dto_TP/FP/FN/TN` di metrics NS-3).

### 3.2 Tafsiran yang diusulkan (paling dekat dengan teks paper)

> Kandidat solusi = **satu node** (identitas node). Objektif = seberapa "normal" perilaku
> node itu menurut tiga kriteria paper. Solusi terbaik (OF minimum) = node paling
> mencurigakan, lalu diisolasi.

Ini pembacaan literal "the best candidate solution is defined as the malicious node".

- Variabel keputusan: `d = 1`, `z ∈ [BL, BU)` kontinu, didekode menjadi indeks node
  kandidat `c(z) = C[⌊z − BL⌋]`, dengan `C` = daftar node kandidat dalam urutan acak
  (permutasi per run; lihat 5.3).
- `OF(z) = −S(c(z))`, dengan `S` = skor kecurigaan (bagian 4). Minimum OF = node
  paling mencurigakan.
- Deteksi banyak node (paper tidak menjelaskan): **isolasi berurutan**. Jalankan DTO,
  terima node terbaik bila lolos aturan penerimaan (K4), keluarkan node itu dari
  kandidat, lalu ulangi. Berhenti bila node terbaik tidak lolos atau kandidat habis.

**Konsekuensi yang harus disampaikan apa adanya.** Dengan pengkodean ini dan kandidat
≤ 100 node, DTO (m = 30, Y = 100, sekitar 9.000 evaluasi) praktis selalu menemukan
**argmax S**. Kemampuan deteksi sepenuhnya ditentukan oleh **S dan aturan penerimaan**,
bukan oleh DTO. Kami akan **menguji** kesetaraan ini (bagian 8) dan melaporkannya
sebagai temuan tentang metode paper. Pengkodean alternatif (vektor keanggotaan
`z ∈ [0,1]^N`) dengan objektif yang terdekomposisi per node juga tereduksi menjadi
ambang per node, jadi tidak mengubah kesimpulan ini (dicatat di K1).

### 3.3 Keluaran

Per node per waktu keputusan: `decision ∈ {malicious, normal, insufficient_evidence}`,
urutan isolasi, `OF`, nilai tiap kriteria, dan jumlah observasi. Disimpan di
`ns3-sim/results/step3/dto_decisions_<n>_s<seed>_<run>.csv`. **Tidak ada kolom label**
di berkas ini. Label hanya digabung di skrip evaluasi.

---

## 4. Pemetaan variabel paper ke telemetry NS-3

> **Catatan status.** Bagian 4–9 adalah **usulan awal sebelum persetujuan reviewer** dan
> dipertahankan sebagai riwayat desain. Bila bertentangan dengan bagian 10, **bagian 10
> (terutama 10.1) yang berlaku**. Butir yang sudah digantikan ditandai
> "[DIGANTIKAN 10.1]": proksi energi `A_j`, bobot 1/3, skor S tiga kriteria, uji
> energi z-score, dan sebagian ablasi di 8.2.

Aturan: hanya kolom observasi tetangga (`obs_*`, `wd_*`, `rx_ok_from`) lewat whitelist
`telemetry_schema` (seperti trust langkah 2). **`self_*` tidak dipakai**, dan label
tidak pernah menjadi masukan.

| Kriteria paper | Variabel kami | Sumber telemetry | Catatan |
|---|---|---|---|
| Packet loss ratio | `PLR_j = D_j / N_j`: rasio paket transit yang tidak diteruskan j | `wd_forwarded`, `wd_forwarded_late`, `wd_unobserved_rxfail`, `wd_unobserved_clean`, `wd_heard_rxfail` (estimasi drop terkoreksi `D_j`, sama dengan `telemetry_trust.corrected_trust`) | Hanya ada untuk node yang pernah menjadi relay (`N_j ≥ N_min`). Audit langkah 2: tanpa forwarded palsu, unobserved_clean 100% benar |
| Packet delivery ratio | `PDR_j = 1 − PLR_j` (rasio penerusan sebagai relay) | sama | **Redundan** dengan PLR untuk satu relay (lihat K2). PDR end-to-end per sumber tidak teramati tetangga: per-flow FlowMonitor hanya ada di simulator, dan menghitungnya sebagai bukti untuk j tidak mencerminkan perilaku j |
| Energy consumption | [DIGANTIKAN 10.1: Not Available, proksi gagal validasi 10.2] `A_j` = **proksi energi transmisi teramati**: `max_i rx_ok_from(i→j) − F_j` per detik aktif, yaitu frame dari j yang di-decode tetangga dikurangi penerusan transit j yang terdengar | `telemetry_links.rx_ok_from`, `wd_forwarded(+late)` | Energi sebenarnya (`self_energy_j`) adalah self-report, sehingga **dilarang**. Proksi ini membuang beban relay (lihat 4.1). Mencakup transmisi asli, retry, ARP. Lihat K3 |

Data yang tersedia: telemetry tervalidasi langkah 2. `_stage1` (27 skenario, rute trust
0.5, sehingga lebih banyak relay malicious teramati), `_stage2` (27), `_ctrl0` (9, tanpa
grayhole = kontrol false positive), dan `_stage1rep`/`_stage1v2` (determinisme).

### 4.1 Cek kelayakan bukti (sudah dilakukan; memakai label untuk evaluasi)

Stage 1, 27 skenario, AUC per skenario (malicious vs normal). Angka dihasilkan ulang
oleh `ml/dto_proxy_validation.py` (keluaran `ml/reports/dto_step3_proxy_validation.json`,
kunci `auc_4_1`). Versi draf sebelumnya memuat angka dari cek ad hoc
(`A_j` 0.901 (0.352), aktivitas 0.670 (0.210)); angka di bawah adalah yang dapat
direproduksi dan menggantikannya:

| Bukti | AUC median (min) | Cakupan malicious |
|---|---|---|
| `PLR_j` (watchdog) | 1.000 (1.000) pada node teramati | 71 / 162 (hanya yang pernah menjadi relay) |
| `rx_ok_from` mentah (aktivitas) | 0.660 (0.000) | 162 / 162 |
| `A_j` = aktivitas − penerusan terdengar | 0.867 (0.000) | 162 / 162 |

- **Pengungkapan tambahan.** Tabel berlabel ini juga ikut menjadi dasar memilih PLR
  sebagai skor utama (selain alasan K2/K3). Karena itu `_stage1` juga bukan data uji
  bersih untuk kriteria PLR; evaluasi utama tetap `_stage2` dan `_ctrl0` (K7).
- Aktivitas mentah tercampur beban relay. Setelah penerusan transit dikurangkan,
  sisanya mencerminkan transmisi milik node sendiri (termasuk flooding penyerang).
- **Pengungkapan.** Pilihan proksi `A_j` dibuat setelah melihat AUC berlabel pada
  `_stage1`. Karena itu `_stage1` bukan data uji yang bersih untuk kriteria energi.
  Evaluasi utama kriteria ini memakai `_stage2` dan `_ctrl0`, dan hasil `_stage1`
  dilaporkan terpisah dengan catatan.

### 4.2 Perilaku penyerang di simulasi kita vs paper

Di simulasi kita, node malicious (10%, ground truth skenario) melakukan **flooding**
(laju kirim 1.5–5×) dan **grayhole** sebagai relay (menjatuhkan 70% transit). Keduanya
adalah desain langkah 1 (U). Paper hanya menyebut kategori umum (konsumsi daya
abnormal, pola transmisi tidak biasa, cloning, spoofing). Cloning dan spoofing di luar
cakupan DTO kita (cloning ditangani 3D Cube, langkah 6).

---

## 5. Alur algoritma DTO yang diusulkan

### 5.1 Skor kecurigaan dan fungsi objektif

> [DIGANTIKAN 10.1] Implementasi akhir memakai `S_j = PLR_j` saja (K2: satu indikator
> delivery reliability; K3: energi Not Available). Kandidat = node dengan `N_j ≥ N_min`.
> Rumus tiga kriteria dan bobot 1/3 di bawah tidak dipakai.

Untuk node kandidat j (`C` = sensor yang punya minimal satu kriteria teramati):

```
L_j  = D_j / N_j                       jika N_j ≥ N_min, selain itu "tidak tersedia"
P_j  = 1 − L_j                         (PDR relay)
A_j  = observed own transmissions/s     (proksi energi)
Ñ    = normalisasi min–max atas kandidat yang memiliki kriteria itu  (sama dgn Norm01 C++)
S_j  = w_E·Ã_j + w_P·(1 − P̃_j) + w_L·L̃_j     kriteria tidak tersedia -> diganti median kandidat (netral)
OF(Z_i) = −S_{c(Z_i)}
```

Bobot: `w_E = w_P = w_L = 1/3`, mengikuti konvensi bobot sama yang dipakai paper untuk
CH (w = 0.25 masing-masing). Akibatnya loss mendapat bobot efektif 2/3 (K2).

### 5.2 DTO (literal pers. 21–31)

```
input : kandidat C (|C| = N_c), S_j, m, Y, rng(seed)
BL, BU = 1, N_c + 1                     # z >= 1 agar langkah multiplikatif (30) tidak mati di 0
Z ~ (22) dgn Rand ∈ [0,1]               # K6
for q = 1..Y:
    nID = max(1, ⌊0.1·m·(1 − q/Y)⌋)     # (24)
    ID  = nID anggota dgn OF terkecil
    P   = 0.01 + 0.9·(1 − q/Y)          # (29)
    for i = 1..m:
        k = acak{1..nID}
        z1 = (25) dgn Rand~U[0,1], Rand1~U[1,2]; klip ke [BL,BU); terima jika OF lebih kecil (26)
        z2 = (27);                       klip; terima (28)
        z3 = (30);                       klip; terima (31)
    perbarui solusi terbaik
return node c(z_best), OF_best
```

- Klip ke batas: paper tidak menyebutnya, tetapi diperlukan karena (22), (25), dan
  (30) bisa keluar batas (U).
- Seluruh RNG ditentukan oleh `(n, seed, run, langkah isolasi)`, sehingga hasilnya
  deterministik.

### 5.3 Deteksi berurutan dan aturan penerimaan

```
C ← kandidat; urutkan acak (permutasi seeded, mencegah bias indeks pada (30))
loop:
    j* = DTO(C)
    if accept(j*):  tandai malicious; C ← C \ {j*}
    else: break
node sisa dgn bukti cukup -> normal; node tanpa bukti apa pun -> insufficient_evidence
```

`accept(j)` (K4). Usulan utama, **tanpa label dan tanpa k a priori**:

- **Uji loss** (bila `N_j ≥ N_min`): posterior Beta `p(q_j | D_j, N_j)` vs baseline
  jaringan `q0` = median `L` kandidat teramati (asumsi mayoritas jujur). Terima bila
  `P(q_j > q0 + δ) ≥ 1 − α/M` (koreksi Bonferroni atas M kandidat), dengan
  `δ = 0.1` dan `α = 0.01`.
- **Uji energi** [DIGANTIKAN 10.1: tidak dipakai karena energi Not Available; hanya
  uji loss yang berlaku]: robust z-score `log(1+A_j)` (median/MAD) > 3.5 (aturan outlier
  Iglewicz–Hoaglin).
- Node diterima bila salah satu uji lolos. Alasan uji ini terpisah dari S: pada node
  normal, loss hampir selalu 0 (MAD = 0), sehingga z-score gabungan tidak stabil.

Varian pembanding **"paper-literal k"**: isolasi tepat `k = ⌈0.1·n⌉` node teratas. Ini
sesuai klaim paper "identified is 10%", tetapi memberi tahu detektor jumlah penyerang,
jadi hanya dipakai untuk pembanding dengan DTO C++ langkah 1.

### 5.4 Waktu keputusan

Offline, dari telemetry kumulatif sampai akhir window w (30 s per window):

- Utama: akhir run (semua window).
- Tambahan: akhir window 0 (t = 30 s), untuk melihat seberapa dini deteksi bisa
  dilakukan.

DTO C++ saat ini berjalan pada t = 8.3 s. Integrasi online ke NS-3 (agar isolasi
memakai keputusan ini) adalah langkah 4–5, bukan langkah ini.

---

## 6. Asumsi dan keterbatasan

1. **Fungsi objektif, pengkodean, multi-deteksi, aturan berhenti, m, Y** tidak ada di
   paper. Semuanya keputusan kami (U/K).
2. **DTO ≈ argmax.** Dengan pengkodean literal, hasil deteksi ditentukan oleh S dan
   aturan penerimaan. DTO tidak menambah daya deteksi (akan diuji).
3. **Cakupan.** Bukti loss hanya ada untuk relay. Pada stage 1, 91 dari 162 node
   malicious tidak pernah menjadi relay, sehingga deteksi mereka bergantung sepenuhnya
   pada proksi energi. Pada stage 2 cakupan relay malicious lebih kecil lagi, karena
   rute menghindarinya.
4. **Proksi energi** bukan energi sebenarnya: mencakup retry dan ARP, dan bergantung
   pada observer yang mendengar. Energi sebenarnya hanya tersedia sebagai self-report,
   yang dilarang.
5. **Redundansi PDR/PLR**: dua dari tiga kriteria paper adalah informasi yang sama
   untuk relay.
6. **Bukti watchdog sama dengan trust.** Kriteria loss memakai data yang sama dengan
   trust langkah 2. Perbedaannya pada fungsi: trust adalah input routing (kontinu),
   sedangkan DTO adalah keputusan diskret untuk IPS. Kami akan membandingkan DTO dengan
   ambang trust sederhana untuk menunjukkan apakah ada nilai tambah.
7. **Pilihan proksi dibuat dengan melihat label** pada `_stage1` (bagian 4.1).
   Evaluasi utama memakai `_stage2` dan `_ctrl0`.
8. **Offline.** Keputusan DTO belum memengaruhi simulasi (isolasi, routing). Dampak
   jaringan baru bisa diukur setelah integrasi (langkah 4–5).
9. **Model penyerang** (flooding + grayhole 0.7) adalah desain kita; angka deteksi
   tidak bisa dibandingkan langsung dengan klaim paper.

---

## 7. Rencana implementasi (setelah desain disetujui)

| Berkas | Isi |
|---|---|
| `ml/dto.py` | Optimizer DTO generik pers. (21)–(31): `DTO(m, Y, bounds, rng).minimize(of)`, dengan log per iterasi (nID, P, best OF). Tidak tahu apa-apa tentang jaringan |
| `ml/dto_detect.py` | Ekstraksi bukti dari telemetry lewat whitelist, skor S, deteksi berurutan, aturan penerimaan, dan varian `paper-literal k`. Keluaran `ns3-sim/results/step3/dto_decisions_*.csv` + meta (parameter, SHA-256 sumber) |
| `ml/dto_eval.py` | **Satu-satunya** tempat label digabung: precision/recall/F1/akurasi/FPR, cakupan, perbandingan baseline, laporan `ml/reports/dto_step3_*.json` |
| `ml/telemetry_schema.py` | Menambah whitelist `DTO_INPUT_LINK_COLUMNS` (`rx_ok_from` + kolom `wd_*`) |
| `ml/tests/test_dto.py` | Uji di bagian 8 |
| `ml/run_dto_step3.py`, `ml/dto_proxy_validation.py` | (ditambahkan saat implementasi) driver semua grup run; validasi proksi energi 4.1/10.2 (evaluasi saja) |
| `docs/PAPER_DEVIATIONS.md` §2e, dashboard | Dokumentasi dan panel DTO (setelah hasil ada) |

Yang **tidak** diubah: `honeycomb-sdwsn.cc` (termasuk `class Dto`), TLDQN, Bi-GAN,
hasil langkah 1–2. Tidak ada run NS-3 baru di langkah 3.

---

## 8. Rencana pengujian

### 8.1 Uji unit (tanpa NS-3)

| Uji | Kriteria lolos |
|---|---|
| Rumus tiap fase (25), (27), (30) dengan RNG tetap | Nilai sama dengan perhitungan tangan |
| Jadwal `nID` (24) dan `P` (29) | Sesuai rumus; `nID ≥ 1` |
| Penerimaan greedy (26), (28), (31) | OF anggota tidak pernah naik; solusi terbaik monoton |
| Batas | Semua posisi dalam `[BL, BU)` |
| Konvergensi sanity pada fungsi uji (sphere, Rastrigin d = 5) | Mendekati optimum; ini cek implementasi, bukan klaim kinerja |
| **Kesetaraan argmax** | DTO pada objektif node menemukan `argmax S` (dibandingkan pencarian exhaustive) |
| Determinisme | Seed sama → keputusan identik |
| Isolasi label | Bukti hanya dari kolom whitelist (uji mutasi kolom `self_*` → keputusan sama); tanpa kolom label di keluaran; skrip deteksi tidak membaca `bigan_decisions` |
| Telemetry sintetis | Skenario dengan relay grayhole dan flooder dikenali; skenario tanpa penyerang → 0 deteksi |

### 8.2 Evaluasi pada telemetry NS-3 (label hanya di `dto_eval.py`)

| Evaluasi | Data | Ukuran |
|---|---|---|
| Kinerja deteksi | `_stage2` (utama), `_stage1` (dengan catatan 4.1) | Precision, recall, F1, akurasi, FPR, untuk semua node dan untuk node dengan bukti |
| False positive tanpa grayhole | `_ctrl0` | FPR. Penyerang tetap melakukan flooding, sehingga kriteria energi masih bisa menemukan mereka; recall loss diharapkan ≈ 0 |
| Pembanding | metrics NS-3 | DTO C++ langkah 1 (`dto_*`, self-report + k a priori), varian `paper-literal k`, ambang trust (`trust < 0.5`), Bi-GAN NS-3 |
| Ablasi | – | Usulan awal: tanpa proksi energi; bobot dedup (1/2, 1/2); m, Y; seed DTO (stabilitas); tanpa permutasi kandidat; δ dan α. **Yang dijalankan** (10.5): `tx_ablation`, `skip`, `paper_k`, m/Y (10/30, 50/200), seed DTO 1–4, window 0. **Tidak dijalankan**: bobot 1/2–1/2 (tidak relevan setelah K2/K3, skor tinggal satu kriteria), tanpa permutasi kandidat, sweep δ dan α |
| Waktu | `_stage1`, `_stage2` | Keputusan di akhir window 0 vs akhir run |
| Determinisme | `_stage1rep` vs `_stage1` | Keputusan identik |

Kriteria keberhasilan **tidak** ditentukan sebagai angka target. Hasil dilaporkan apa
adanya, termasuk bila DTO tidak lebih baik dari ambang trust sederhana.

---

## 9. Keputusan yang perlu disetujui reviewer

> Tabel ini adalah usulan awal. Keputusan reviewer dan penerapannya ada di **10.1**;
> K2, K3, dan K4 diputuskan berbeda dari usulan di bawah.

| ID | Pertanyaan | Usulan |
|---|---|---|
| K1 | Pengkodean kandidat solusi | Satu kandidat = satu node (literal "best candidate = malicious node"), disertai pengungkapan bahwa DTO ≈ argmax |
| K2 | Bobot tiga kriteria walau PDR dan PLR redundan | [DIGANTIKAN 10.1: hanya PLR] Literal 1/3 masing-masing (konvensi bobot sama paper); ablasi 1/2–1/2 |
| K3 | Energi tanpa `self_*` | [DIGANTIKAN 10.1: Not Available] Proksi `A_j` (transmisi sendiri teramati tetangga), plus ablasi tanpa energi. Alternatif lain: memakai `self_energy_j` sebagai "laporan node" dengan peringatan kebocoran (**tidak** disarankan) |
| K4 | Aturan berhenti multi-deteksi | [DIGANTIKAN 10.1: hanya uji Beta loss] Utama: uji statistik tanpa label (loss: Beta + Bonferroni; energi: robust z > 3.5). Pembanding: `paper-literal k = 10%` |
| K5 | `m`, `Y`, `N_min` | m = 30 (U; C++ langkah 1 memakai m = jumlah node karena pengkodeannya berbeda), Y = 100 (sama dengan C++ langkah 1), N_min = 10 (sama dengan aturan dashboard) |
| K6 | `Rand ∈ [0, 2]` pada (22) | Ditafsirkan `[0, 1]` (kemungkinan salah ketik, karena `[0,2]` melampaui batas atas); dicatat sebagai deviasi |
| K7 | Data evaluasi utama | `_stage2` + `_ctrl0` (karena proksi dipilih dengan melihat `_stage1`) |
| K8 | Cakupan langkah 3 | Offline saja; integrasi ke NS-3 (isolasi memakai DTO baru) di langkah 4–5 |

---

## 10. Hasil implementasi (offline, telemetry langkah 2)

Reproduksi: `.venv/bin/python ml/run_dto_step3.py` (sekitar 2 menit, tanpa NS-3).
**Catatan pembekuan (bagian 11):** driver ini memakai default kode `b_max = 0.8`, jadi
keluarannya yang di-commit (`ns3-sim/results/step3/`, `ml/reports/dto_step3_*.json`)
adalah **varian K9**. Metode utama (pra-K9) dijalankan dengan command di 11.2.
Keluaran: `ns3-sim/results/step3/<grup>/dto_decisions_*.csv` + `dto_meta_*.json`
(konfigurasi, SHA-256 telemetry sumber, log tiap langkah DTO). Evaluasi:
`ml/reports/dto_step3_<grup>.json`, ringkasan `ml/reports/dto_step3_summary.json`.

### 10.1 Keputusan yang disetujui dan cara penerapannya

| ID | Keputusan reviewer | Penerapan |
|---|---|---|
| K1 | 1 kandidat = 1 node | `z ∈ [1, N_c + 1)` didekode menjadi `C[⌊z − 1⌋]`; `OF = −S` |
| K2 | PDR dan PLR tidak dihitung dua kali | Satu indikator delivery reliability, `PLR_j = D_j / N_j` |
| K3 | Tanpa `self_*`; proksi energi hanya jika valid dan tidak disamakan dengan residual energy | Validasi proksi (bagian 10.2) **gagal**, sehingga kriteria energi = **Not Available**. Aktivitas TX hanya sebagai ablasi berlabel "bukan energi" |
| K4 | Berhenti secara statistik, tanpa label | Uji Beta `P(q_j > q0 + 0.1) ≥ 1 − 0.01/M` (q0 = median PLR kandidat), berhenti pada kegagalan pertama |
| K5 | m = 30, Y = 100, N_min = 10 | Konfigurasi reproduksi (bukan dari paper), dicatat di setiap `dto_meta_*.json` |
| K6 | Rand (22) ~ U(0,1) | Diterapkan; asumsi tercatat di kode (`[ASUMSI K6]`) |
| K7 | Evaluasi utama stage 2 + kontrol | `stage2`, `ctrl0`; `stage1` sekunder |
| K8 | Offline | Tidak ada perubahan C++/NS-3 |
| K9 | Observer b ≥ 0.8 tidak memberi bukti N_j; target tanpa bukti cukup = `insufficient_evidence`; trust/routing langkah 2 tetap | `dto_detect.evidence(b_max=0.8)`; rincian dan dampak di 10.8 |
| K10 | Energi tetap Not Available; tanpa proksi baru | Ditunda ke langkah 4–5 (perubahan telemetry) |

### 10.2 Validasi proksi energi (K3)

Kolom `self_*` dipakai **hanya sebagai alat ukur validasi proksi**, bukan sebagai
masukan deteksi. Skrip: `ml/dto_proxy_validation.py` (keluaran
`ml/reports/dto_step3_proxy_validation.json`, kunci `spearman_10_2`). Data: `_stage1`
(27 skenario), `_stage2` (27), `_ctrl0` (9). Nilai = median korelasi Spearman per
skenario:

| Proksi | Data | vs paket asli node | vs MPDU dipancarkan | vs energi radio |
|---|---|---|---|---|
| `A_j` (frame terdengar − penerusan) | stage1 / stage2 / ctrl0 | 0.405 / 0.446 / 0.386 | – | 0.094 / 0.073 / 0.039 |
| `rx_max` (frame dari j yang di-decode tetangga) | stage1 / stage2 / ctrl0 | – | 0.987 / 0.998 / 0.995 | 0.134 / 0.091 / 0.125 |

`rx_max` valid sebagai ukuran **aktivitas TX**, tetapi tidak mewakili energi. Pada model
radio ini energi didominasi arus RX/idle. Tidak ada besaran yang teramati tetangga
yang valid sebagai energi, sehingga kriteria energi paper **Not Available** dalam
reproduksi ini.

### 10.3 Pemisahan fakta paper, asumsi reproduksi, dan keputusan implementasi

| Butir | Fakta paper | Asumsi reproduksi | Keputusan implementasi |
|---|---|---|---|
| Pers. (21)–(31), Algoritma 2 | ✔ diterapkan literal (`ml/dto.py`, diuji per persamaan) | – | – |
| Kriteria energi, PDR, PLR | ✔ disebut | PDR = 1 − PLR (K2) | energi Not Available (K3) |
| Best candidate = node malicious | ✔ | 1 kandidat = 1 node (K1) | – |
| Rand (22) | tertulis [0, 2] | U(0,1) (K6) | – |
| nID (24) | `[0.1n(1 − q/Y)]` | floor, minimal 1 | – |
| Instruktur | "based on the value of objective function" | nID anggota terbaik | dihitung ulang per anggota |
| k_i fase 2 | ID_{k_i} | sama dengan fase 1 | – |
| Penanganan batas | tidak disebut | – | klip ke [BL, BU) |
| Multi-deteksi, aturan berhenti | tidak disebut | – | isolasi berurutan + uji Beta (K4) |
| m, Y, N_min, δ, α | tidak disebut | – | 30, 100, 10, 0.1, 0.01 (K5) |
| Keandalan observer | tidak disebut | – | observer b ≥ 0.8 dikecualikan dari bukti (K9) |
| Waktu eksekusi | tidak disebut | – | offline: akhir run dan akhir window 0 |

### 10.4 Uji

`ml/tests/test_dto.py` berisi 18 uji pra-K9 (127 uji repo lolos saat itu); setelah K9
menjadi 29 uji, total repo 138 lolos (10.8). Cakupan uji pra-K9:

- rumus tiap persamaan dengan RNG tetap;
- jadwal nID dan P;
- solusi terbaik monoton dan posisi dalam batas;
- sanity check pada fungsi sphere dan Rastrigin;
- kesamaan dengan argmax (30/30 skenario acak);
- determinisme;
- deteksi grayhole sintetis, dan nol deteksi tanpa serangan;
- isolasi label: sumber detektor tidak membaca label, `self_*`, atau audit; mutasi
  kolom non-whitelist tidak mengubah keputusan.

### 10.5 Hasil deteksi

> **Status.** Tabel pertama di bawah adalah hasil **pra-K9** (dipertahankan sebagai
> riwayat). **Keputusan final (bagian 11): pra-K9 adalah metode utama**, jadi tabel ini
> adalah hasil metode utama (diverifikasi ulang dengan `--b-max 0`, 11.3). Hasil K9
> (varian pembanding) ada di 10.8.

Angka berikut adalah pool semua skenario. Kolom "semua" menghitung node
`insufficient_evidence` sebagai prediksi normal.

| Run / varian | TP | FP | FN | Precision | Recall (semua) | F1 | FPR | Recall (node berbukti) | Cakupan malicious |
|---|---|---|---|---|---|---|---|---|---|
| **stage2 / main** | 33 | 0 | 129 | 1.000 | 0.204 | 0.338 | 0.000 | 0.971 | 34/162 |
| stage2 / skip | 33 | 0 | 129 | 1.000 | 0.204 | 0.338 | 0.000 | 0.971 | 34/162 |
| stage2 / paper_k (k = 10%) | 33 | 129 | 129 | 0.204 | 0.204 | 0.204 | 0.088 | 0.971 | 34/162 |
| stage2 / tx_ablation | 101 | 442 | 61 | 0.186 | 0.623 | 0.287 | 0.303 | 0.623 | 162/162 |
| stage2 / main, window 0 (t ≤ 30 s) | 33 | 0 | 129 | 1.000 | 0.204 | 0.338 | 0.000 | 0.971 | 34/162 |
| **ctrl0 / main** (tanpa grayhole) | 0 | 0 | 54 | – | 0.000 | – | 0.000 | 0.000 | 24/54 |
| ctrl0 / paper_k | 6 | 48 | 48 | 0.111 | 0.111 | 0.111 | 0.099 | 0.250 | 24/54 |
| stage1 / main (sekunder) | 71 | 0 | 91 | 1.000 | 0.438 | 0.609 | 0.000 | 1.000 | 71/162 |

Pembanding pada skenario yang sama (semua node):

| Pembanding | stage2 P / R / F1 / FPR | ctrl0 P / R / F1 / FPR | Catatan |
|---|---|---|---|
| DTO C++ langkah 1 | 0.852 / 0.852 / 0.852 / 0.016 | 0.833 / 0.833 / 0.833 / 0.019 | **Tidak sebanding**: memakai self-report (laju kirim, energi) dan k = 10% a priori |
| Ambang trust telemetry (< 0.5, N ≥ 10) | 1.000 / 0.198 / 0.330 / 0.000 | – / 0.000 / – / 0.000 | Bukti watchdog yang sama |
| Bi-GAN NS-3 (per node) | 0.844 / 0.568 / 0.679 / 0.012 | 0.842 / 0.593 / 0.696 / 0.012 | Fitur NSL-KDD per node, bukan perilaku jaringan |

### 10.6 Temuan

> Temuan ini berdasarkan hasil pra-K9. Kesimpulan kualitatifnya tetap berlaku; angka
> pasca-K9 dan perubahannya ada di 10.8.

1. **Pada node yang punya bukti, DTO hampir sempurna.** Di stage2 ada 33 TP dari 34
   malicious berbukti, tanpa false positive. Kontrol tanpa grayhole menghasilkan nol
   deteksi, jadi tidak ada false positive akibat kanal.
2. **Recall rendah karena cakupan, bukan karena DTO.** Stage2 hanya mengamati 34 dari
   162 node malicious, karena rute tahap-2 menghindari relay malicious. Ini
   ketegangan nyata antara routing aman dan bukti deteksi. Stage1 (trust 0.5) mengamati
   71/162.
3. **Flooding tidak terdeteksi tanpa kriteria energi.** Kriteria energi
   Not Available (10.2). Proksi aktivitas TX memang menangkap sebagian flooder, tetapi
   FPR-nya 0.30, karena aktivitas TX didominasi beban relay. Proksi ini tidak layak
   dipakai.
4. **DTO ≈ argmax, sesuai prediksi bagian 3.2.**
   - Varian main menemukan argmax 60/60 langkah. Hasilnya hampir sama dengan ambang
     trust sederhana (33 vs 32 TP, keduanya 0 FP; kesamaan per node tidak dibandingkan).
   - Pada `tx_ablation` (banyak kandidat dengan skor kontinu mirip), DTO meleset dari
     argmax 10 dari 1.265 langkah: stage2 4/570, ctrl0 1/194, stage1 5/501. DTO adalah
     aproksimasi stokastik. Varian lain (main, skip, paper_k) menemukan argmax di
     semua langkah.
   - Keputusan identik untuk seed DTO 1–4 (27/27 masing-masing) dan untuk
     (m, Y) = (10, 30) dan (50, 200) (27/27).
5. **`paper_k` (k = 10% a priori) merusak precision** (0.204), karena memaksa isolasi
   node normal ketika bukti hanya ada untuk sedikit node.
6. **Deteksi dini.** Keputusan di akhir window 0 (t ≤ 30 s) identik dengan akhir run,
   karena trafik sensor terkonsentrasi di awal simulasi.
7. **Determinisme.** Keputusan dari run NS-3 ulang (`stage1rep`) identik 3/3.
8. **Satu FN berbukti (n = 80, s = 2, node 3)**, dengan N = 50 dan estimasi drop 0,
   disebabkan **observer yang tidak informatif**:
   - Observer 59 punya laju kegagalan kebetulan b = 0.94. Ke-33 drop grayhole (audit)
     semuanya jatuh ke kategori ambigu, sehingga U = 0 dan `D = U/(1 − b) = 0`.
   - Kasus ini terjadi pada 2 node malicious dan 0 node normal di 54 run.
   - Ini keterbatasan estimator bukti langkah 2 untuk observer dengan b mendekati 1.
     Usulan perbaikan ada di K9. **Status:** K9 disetujui dan diterapkan; node ini
     sekarang `insufficient_evidence` (10.8), dengan efek samping yang dilaporkan di sana.
9. **Keterbatasan laten aturan berhenti (tidak monoton).** DTO memilih kandidat dengan
   PLR tertinggi, sedangkan uji Beta juga bergantung pada N_j. Kandidat dengan PLR
   tinggi tetapi N kecil bisa gagal uji, lalu varian `main` berhenti, padahal kandidat
   lain dengan PLR sedikit lebih rendah tetapi N besar mungkin lolos. Varian `skip`
   (lanjut setelah gagal) dibuat untuk memeriksa ini. Pada data saat ini keputusan
   `skip` identik dengan `main` per node di semua run (stage2 27/27, ctrl0 9/9,
   stage1 27/27), jadi belum berdampak. Kasus ini tetap perlu dicek bila data berubah.

### 10.7 Keputusan lanjutan (diputuskan reviewer)

Keputusan: **K9 disetujui** (diterapkan, lihat 10.8). **K10 ditunda**: energi tetap
Not Available di langkah 3, tidak ada proksi energi baru; perbaikan telemetry di
langkah 4–5. Tabel usulan asli:

| ID | Pertanyaan | Usulan |
|---|---|---|
| K9 | Observer dengan b mendekati 1 membuat "tidak ada drop" padahal buktinya tidak informatif | Bukti dari observer dengan `b_i ≥ 0.8` tidak dihitung untuk N_j, sehingga node seperti di atas menjadi `insufficient_evidence`, bukan `normal`. Hanya memengaruhi DTO; trust dan routing langkah 2 tidak diubah. Alternatif: estimator berbasis defisit penerusan terdengar `D = N − F/(1 − c_i)`, yang memerlukan estimasi laju tabrakan c_i (lebih kompleks) |
| K10 | Kriteria energi | Tetap Not Available di langkah 3. Kriteria ini hanya bisa dipulihkan bila telemetry memisahkan frame milik node sendiri dari frame transit, yang berarti perubahan telemetry dan run NS-3 baru. Ditunda ke langkah 4–5 bila disetujui |

### 10.8 K9: pengecualian observer tidak andal (diterapkan; status final = varian pembanding, bagian 11)

**Aturan.** Observer i dengan `b_i ≥ 0.8` tidak memberi bukti untuk `N_j` dan `D_j`
(`ml/dto_detect.py`, `B_MAX_OBSERVER`, opsi `--b-max`; tercatat di setiap
`dto_meta_*.json` sebagai `b_max_observer` dan `excluded_observers`). Target yang
setelah itu punya `N_j < N_min` berstatus `insufficient_evidence`, bukan `normal`.
Kolom keputusan baru `n_watched_excluded` mencatat watch yang dibuang per target.

**Makna b.** `b_i = Σ wd_heard_rxfail / Σ (wd_forwarded + wd_forwarded_late)`, diukur
hanya pada watch yang **terdengar** (penerusan yang benar-benar terjadi) dan hanya dari
kegagalan terima PHY observer i sendiri di window watch. Drop dan packet loss jaringan
tidak masuk pembilang maupun penyebut, jadi b adalah kegagalan observasi milik
observer. Uji "menambah drop relay tidak mengubah b" hanya mengonfirmasi rumus ini,
bukan bukti empiris tambahan. **Batas makna b:** kegagalan terima observer juga
dipicu tabrakan dari pemancar lain di sekitarnya, jadi b mengukur kondisi kanal lokal
observer, bukan cacat observer murni dan bukan perilaku target. Konsekuensinya,
observer di area padat lebih mungkin dikecualikan walau target-nya jujur (diuji:
`test_collision_driven_b_excludes_dense_observer`), dan K9 membuang bukti benar
maupun salah dari observer tersebut (lihat 6 TP yang hilang di bawah). Observer tanpa
watch terdengar (b tidak terukur, memakai b gabungan langkah 2) tidak pernah
dikecualikan (diuji sintetis). **Koreksi (tinjauan 10.9):** versi sebelumnya menulis
"kasus ini 0 di semua run"; yang benar, ada 1.268 entri observer tanpa watch terdengar
di stage2 + ctrl0 + stage1, tetapi **tidak satu pun punya watch** (F + A + U = 0), jadi
mereka tidak pernah menyumbang bukti dan aturan ini tidak teruji oleh data nyata.

**Yang tidak berubah.** `telemetry_trust.py` (trust dan routing langkah 2),
pembanding `trust_thresh`, kolom `tx` (`rx_ok_from`, hanya ablasi). Estimator K9 dengan
nol observer dikecualikan identik dengan `corrected_trust` pada 126 kasus telemetry
nyata (63 run × semua window/window 0), diuji di suite
(`test_estimator_without_exclusion_equals_step2_on_real_telemetry`) dan pada data
sintetis.

**Uji (`ml/tests/test_dto.py`, 11 uji baru, total `test_dto` 29, total repo 138 lolos).**

Definisi "terdampak" yang dipakai uji dan dokumen (dinyatakan eksplisit):

- **Malicious terdampak** = node malicious yang keputusannya berubah karena K9. Ada dua
  jenis: (a) **2 node** berbukti yang pra-K9 `normal` menjadi `insufficient_evidence`
  (kasus sasaran K9), dan (b) **6 TP** `malicious` yang menjadi
  `insufficient_evidence` (efek samping). Jadi total 8 node malicious berubah keputusan.
- **Normal terdampak** = node normal yang berubah ke atau dari `malicious`: **0**. Di
  luar itu, **30 node normal** berubah `normal` → `insufficient_evidence`; ini tidak
  mengubah TN maupun FPR pada metrik biner, tetapi mengurangi cakupan keputusan.

- Sintetis: observer b = 0.94 dengan semua drop di kategori ambigu → pra-K9 `normal`,
  pasca-K9 `insufficient_evidence`; target dengan observer andal tidak berubah; batas
  b = 0.80 dikecualikan, 0.79 tidak; `b_max=None` identik dengan langkah 2; trust
  langkah 2 tetap memakai observer tersebut.
- Telemetry NS-3 (label hanya untuk evaluasi, setelah keputusan), varian main,
  stage2 + ctrl0 + stage1:
  - (a) **2 node malicious** berbukti yang pra-K9 diputuskan `normal` menjadi
    `insufficient_evidence`: stage2 n=80 s=2 node 3 (FN berbukti grayhole di 10.6 butir
    8) dan ctrl0 n=100 s=1 node 32. Node ctrl0 ini berada di kontrol **tanpa grayhole**,
    jadi tidak men-drop; ia bukan deteksi yang terlewat, hanya dihitung FN pada metrik
    berlabel. Kasus sasaran yang benar-benar menyembunyikan drop grayhole hanya 1.
  - (b) **6 TP** malicious hilang (tabel efek samping di bawah).
  - **0 node normal** berubah ke atau dari `malicious` (tidak ada FP baru maupun FP
    hilang); 30 node normal berubah `normal` → `insufficient_evidence`. Tidak ada node
    yang berpindah ke `normal`, dan tidak ada jenis transisi lain.
  - Observer tanpa b terukur tidak dikecualikan; observer di area padat ikut
    dikecualikan karena tabrakan (keduanya diuji).

**Efek samping terukur (hasil negatif, dilaporkan apa adanya).** Pengecualian berlaku
untuk semua target, bukan hanya kasus di atas:

| Transisi (varian main) | stage2 | ctrl0 | stage1 |
|---|---|---|---|
| malicious: `normal` → `insufficient_evidence` | 1 | 1 | 0 |
| malicious: `malicious` (TP) → `insufficient_evidence` | **2** | 0 | **4** |
| normal: `normal` → `insufficient_evidence` | 9 | 6 | 15 |
| normal: berubah ke / dari `malicious` | 0 | 0 | 0 |

TP yang hilang (stage2 n=70 s=3 node 5, n=90 s=3 node 3; stage1 n=70 s=2 node 17,
n=70 s=3 node 5, n=80 s=2 node 3, n=100 s=1 node 32) adalah node yang bukti drop-nya
berasal dari observer b ≥ 0.8. Pada observer seperti ini estimator langkah 2 memakai
`D = A + U` (b = 1) atau `U/(1 − b)` (penguatan besar), dan pada kasus tersebut
hasilnya kebetulan benar. Jadi bukti observer b tinggi tidak informatif ke dua arah:
bisa menyembunyikan drop (kasus FN) dan bisa juga menghasilkan deteksi benar. K9 memilih
"tidak memutuskan" untuk keduanya.

**Hasil pasca-K9 (varian pembanding eksperimental; bukan metode utama, lihat bagian 11).**

| Run / varian | TP | FP | FN | Precision | Recall (semua) | F1 | FPR | Recall (node berbukti) | Cakupan malicious |
|---|---|---|---|---|---|---|---|---|---|
| **stage2 / main** | 31 | 0 | 131 | 1.000 | 0.191 | 0.321 | 0.000 | 1.000 | 31/162 |
| stage2 / skip | 31 | 0 | 131 | 1.000 | 0.191 | 0.321 | 0.000 | 1.000 | 31/162 |
| stage2 / paper_k | 31 | 131 | 131 | 0.191 | 0.191 | 0.191 | 0.090 | 1.000 | 31/162 |
| stage2 / tx_ablation | 100 | 445 | 62 | 0.183 | 0.617 | 0.283 | 0.305 | 0.617 | 162/162 |
| stage2 / main, window 0 | 31 | 0 | 131 | 1.000 | 0.191 | 0.321 | 0.000 | 1.000 | 31/162 |
| **ctrl0 / main** | 0 | 0 | 54 | – | 0.000 | – | 0.000 | 0.000 | 23/54 |
| ctrl0 / paper_k | 6 | 48 | 48 | 0.111 | 0.111 | 0.111 | 0.099 | 0.261 | 23/54 |
| ctrl0 / tx_ablation | 29 | 156 | 25 | 0.157 | 0.537 | 0.243 | 0.321 | 0.537 | 54/54 |
| stage1 / main (sekunder) | 67 | 0 | 95 | 1.000 | 0.414 | 0.585 | 0.000 | 1.000 | 67/162 |
| stage1 / paper_k | 67 | 95 | 95 | 0.414 | 0.414 | 0.414 | 0.065 | 1.000 | 67/162 |
| stage1 / tx_ablation | 87 | 385 | 75 | 0.184 | 0.537 | 0.274 | 0.264 | 0.537 | 162/162 |

Pembanding tidak berubah (stage2: trust_thresh P 1.000 / R 0.198; Bi-GAN NS-3
0.844 / 0.568; DTO C++ 0.852, tidak sebanding). Setelah K9, recall DTO stage2 (0.191)
sedikit **di bawah** ambang trust sederhana (0.198), karena ambang trust tetap memakai
observer b tinggi.

Diagnostik pasca-K9:

- Determinisme `stage1rep` 3/3; seed DTO 1–4: 27/27 masing-masing.
- `main` = `skip` per node di semua run (stage2 27/27, ctrl0 9/9, stage1 27/27).
- DTO menemukan argmax di semua langkah main/skip/paper_k; `tx_ablation` meleset
  4/572 (stage2), 1/194 (ctrl0), 7/499 (stage1).
- **Sensitivitas (m, Y) turun:** (50, 200) 27/27, tetapi (10, 30) **26/27**. Pada stage2
  n=70 s=3, dengan m=10, Y=30 DTO tidak menemukan argmax di langkah pertama (memilih
  kandidat skor 0), uji gagal, dan varian main berhenti sehingga node 6 (PLR 0.74)
  tidak terdeteksi. Ini kasus nyata dari keterbatasan aturan berhenti (10.6 butir 9)
  yang dipicu aproksimasi stokastik DTO dengan populasi/iterasi kecil, bukan efek
  langsung K9. Konfigurasi utama (30, 100) tidak terdampak.

### 10.9 Tinjauan K9: dapatkah bukti positif dipertahankan? (diinvestigasi; tidak ada perubahan kode)

Pertanyaan reviewer: dapatkah K9 mempertahankan bukti positif dari observer b ≥ 0.8
(observer mendengar target meneruskan) sambil membuang hanya observasi yang hilang atau
ambigu (yang bisa dijelaskan tabrakan atau kondisi terima lokal)?

**Status dokumen.** Bagian ini memisahkan (i) **hasil terukur** pada telemetry langkah 2,
(ii) **kandidat yang dievaluasi lalu ditolak**, dan (iii) **rekomendasi**. Implementasi
DTO, hasil di 10.8, dan commit `575e7a2` **tidak diubah**. Yang ditambahkan hanya uji
karakterisasi di `ml/tests/test_dto.py` (kandidat yang ditolak ada di sana sebagai helper
uji `_positive_only_evidence`, tidak dipakai DTO).

#### 10.9.1 Semantik telemetry yang relevan (dari `docs/TELEMETRY.md` dan audit langkah 2)

| Kategori watch | Arti | Keandalan (audit langkah 2) |
|---|---|---|
| F (`forwarded`, `forwarded_late`) | Observer mendengar target meneruskan: **bukti positif penerusan** | Tidak ada F palsu |
| U (`unobserved_clean`) | Tidak terdengar, tanpa kegagalan terima di observer: **bukti negatif bersih** | 100% benar-benar tidak dipancarkan |
| A (`unobserved_rxfail`) | Tidak terdengar, dan observer sempat gagal terima di window: **observasi hilang/ambigu** | Campuran drop dan tabrakan |

Asimetrinya: paket yang di-drop jatuh ke A dengan peluang b (ada kegagalan terima di
window), sedangkan paket yang diteruskan jatuh ke A hanya bila frame itu sendiri gagal.
Karena itu, pada observer dengan b tinggi, **drop hampir selalu tersembunyi di A**, dan
F tidak memberi informasi tentang berapa banyak paket yang tidak diteruskan.

Tentang tabrakan: b memang mencakup tabrakan di sekitar observer, bukan hanya cacat
observer. Tetapi untuk keperluan ini besaran yang relevan justru b: peluang sebuah drop
tidak terlihat sebagai U adalah b, apa pun penyebab kegagalan terimanya. Jadi definisi
b tidak perlu diubah; yang dipersoalkan adalah apa yang boleh disimpulkan dari observer
dengan b tinggi.

#### 10.9.2 Mengapa 6 TP hilang (terukur; label/audit hanya untuk evaluasi)

| Kasus | Observer (b) | F | A | U | Mekanisme D pra-K9 | N_eff ≈ Σ N_i(1 − b_i) |
|---|---|---|---|---|---|---|
| K9: stage2 n=80 s=2 node 3 | 59 (0.941) | 17 | 33 | 0 | U/(1−b) = 0 → **D = 0 (FN)** | 2.9 |
| K9: ctrl0 n=100 s=1 node 32 | 33 (0.948) | 50 | 0 | 0 | D = 0 (tanpa grayhole) | 2.6 |
| TP: stage2 n=70 s=3 node 5 | 22 (1.000) | 25 | 51 | 0 | b = 1 → D = A + U = 51 | 0.0 |
| TP: stage2 n=90 s=3 node 3 | 59 (0.889) | 18 | 29 | 3 | 3 × 9.0 = 27 | 5.6 |
| TP: stage1 n=70 s=2 node 17 | 12 (1.0), 13 (0.909), 67 (0.846), 68 (1.0) | 87 | 195 | 5 | A + U pada b = 1; 2 × 11.0; 2 × 6.5 | 12.2 |
| TP: stage1 n=70 s=3 node 5 | 22 (0.833) | 30 | 54 | 7 | 7 × 6.0 = 42 | 15.2 |
| TP: stage1 n=80 s=2 node 3 | 2, 9, 59 (semua 1.000) | 67 | 148 | 1 | b = 1 → D = A + U | 0.0 |
| TP: stage1 n=100 s=1 node 32 | 33 (0.869) | 8 | 8 | 3 | 3 × 7.6 = 22.9 | 2.5 |

Audit simulator mengonfirmasi bahwa semua A dan U pada kasus-kasus ini adalah drop
grayhole (`j_ip_drop_route_error`) dan semua F memang terdengar (`j_tx_heard`).

Kesimpulan terukur:

1. Keenam TP terdeteksi pra-K9 **bukan karena bukti positif**, tetapi karena kategori
   ambigu A ditafsirkan sebagai drop. Ada dua jalur: cabang b = 1 (`D = A + U`, 3
   kasus seluruhnya atau sebagian) dan penguatan `U/(1 − b)` dengan U kecil (2–7 watch
   bersih dikalikan 6–11). Di setiap kasus A > U (minimum 8 vs 3).
2. Mekanisme yang sama menghasilkan FN sasaran K9: dengan b = 0.941 dan U = 0, D = 0.
   Benar atau salahnya hasil pra-K9 bergantung pada apakah U kebetulan > 0 atau b
   kebetulan tepat 1.000. Tanpa label atau audit (yang dilarang dalam inferensi), kedua
   kelompok tidak bisa dibedakan.
3. Uji Beta memperlakukan D hasil penguatan (mis. 27 dari U = 3) seolah 27 drop yang
   teramati langsung. Jadi kepastian posterior pada 6 TP itu berlebihan, walaupun
   keputusannya kebetulan benar.

#### 10.9.3 Kandidat "pertahankan bukti positif" (dievaluasi, **ditolak**)

Kandidat: observer b ≥ 0.8 hanya menyumbang watch tak-ambigu, `N += F + U`, `D += U`;
A dibuang. Observer lain tetap seperti langkah 2. Varian main, label hanya untuk evaluasi:

| Run | Metode | TP | FP | FN | Recall | Cakupan malicious | `insufficient_evidence` | FN berbukti (`normal` & malicious) |
|---|---|---|---|---|---|---|---|---|
| stage2 | pra-K9 | 33 | 0 | 129 | 0.204 | 34/162 | 1043 | 1 |
| stage2 | K9 (pembanding, 10.8) | 31 | 0 | 131 | 0.191 | 31/162 | 1055 | 0 |
| stage2 | kandidat bukti positif | 31 | 0 | 131 | 0.191 | 34/162 | 1043 | **3** |
| ctrl0 | pra-K9 | 0 | 0 | 54 | 0.000 | 24/54 | 312 | 24 |
| ctrl0 | K9 | 0 | 0 | 54 | 0.000 | 23/54 | 319 | 23 |
| ctrl0 | kandidat | 0 | 0 | 54 | 0.000 | 24/54 | 312 | 24 |
| stage1 | pra-K9 | 71 | 0 | 91 | 0.438 | 71/162 | 930 | 0 |
| stage1 | K9 | 67 | 0 | 95 | 0.414 | 67/162 | 949 | 0 |
| stage1 | kandidat | 67 | 0 | 95 | 0.414 | 71/162 | 930 | **4** |

(`insufficient_evidence` dihitung atas semua sensor. FN berbukti di ctrl0 adalah node
malicious yang tidak men-drop karena kontrolnya tanpa grayhole; itu bukan deteksi yang
terlewat.)

- Kandidat memulihkan **0 dari 6 TP**. Keenamnya berubah dari `malicious` menjadi
  `normal`, dan 2 kasus K9 kembali `normal`. Jadi kandidat lebih buruk daripada K9 dan
  juga daripada pra-K9: menghasilkan 7 FN berbukti grayhole, yaitu node yang yakin
  diputuskan normal padahal men-drop 70% transit.
- Kandidat memang memulihkan cakupan dan jumlah `insufficient_evidence` ke angka pra-K9,
  termasuk 30 node normal di 10.8. Tetapi keputusan `normal` itu ditopang oleh sampel F
  yang bias, sama seperti untuk node malicious, bukan oleh bukti yang sah.
- FP = 0 untuk ketiga metode di semua run.
- Contoh sintetis (diuji): b = 0.9, q = 0.7 → PLR kandidat 7/37 = 0.19.
  Secara umum PLR kandidat ≈ q(1 − b) / (q(1 − b) + (1 − q)(1 − c)), dengan c = peluang
  gagal frame penerusan itu sendiri; bias ke bawah kuat ketika b ≫ c.

**Jawaban.** Pemisahan bukti positif vs hilang **valid secara semantik** (F dan U andal,
A tidak), tetapi **mempertahankan bukti positif tidak sah sebagai dasar keputusan** pada
observer b tinggi. Alasannya, bukti positif tanpa bukti negatif yang setara adalah sampel
bias: drop disaring keluar ke A. Bukti positif yang benar-benar dimiliki observer ini
hanya membuktikan "sebagian paket diteruskan", bukan "laju drop rendah".

#### 10.9.4 Rekomendasi

1. **Tidak ada perubahan kode yang aman** berdasarkan bukti yang ada. Implementasi K9 di
   `575e7a2` dipertahankan apa adanya sebagai baseline pembanding.
2. K9 (b_max = 0.8) diberi status **varian eksperimental, bukan metode DTO final**. Varian
   ini menghilangkan FN berbukti, tetapi membayar dengan 6 TP dan cakupan.
   Pra-K9 (`--b-max 0`) tetap tersedia sebagai pembanding. Pemilihan metode final
   menunggu keputusan reviewer. **[Diputuskan, bagian 11: pra-K9 = metode utama; K9 =
   varian pembanding; N(1 − b) ditunda.]**
3. Opsi lanjutan yang **belum diimplementasikan dan belum divalidasi** (perlu
   persetujuan, karena mengubah uji/skor): perlakukan observer b tinggi lewat **ukuran
   sampel efektif** `N_eff,i = N_i(1 − b_i)` (jumlah watch yang secara efektif bisa
   memperlihatkan drop), bukan dengan membuang atau memakai penuh. Indikasi pada tabel
   10.9.2: 2 kasus K9 punya N_eff < 10 (tetap `insufficient_evidence`); dari 6 TP, 2
   (stage1 n=70 s=2 node 17: 12.2; n=70 s=3 node 5: 15.2) punya N_eff ≥ 10, dan 4
   lainnya tidak. Dampaknya pada node normal, FP, dan bentuk uji Beta yang sah untuk N
   pecahan belum dianalisis. Ini bukan klaim hasil.
4. Pemulihan langsung bukti drop pada observer b tinggi memerlukan telemetry yang
   membedakan kegagalan frame penerusan itu sendiri (c) dari kegagalan lain di window.
   Itu perubahan telemetry, di luar langkah 3 (sama seperti K10).

**Uji baru (8; total repo 146 lolos):** `TestK9PositiveEvidenceReview` (2, sintetis:
bias bukti-positif dan mekanisme FN U = 0) dan `TestK9PositiveEvidenceOnTelemetry` (6,
telemetry nyata):
- 6 TP bergantung pada A (cabang b = 1 atau U ≤ 7 diperkuat);
- 2 kasus K9 tanpa U;
- kandidat mengubah tepat 6 TP menjadi `normal`, dengan 0 FP;
- 2 kasus K9 tetap `normal` pada kandidat;
- observer tanpa b terukur tidak punya watch (1.268 entri);
- b observer yang dikecualikan dihitung dari watch terdengar.

Uji K9 sebelumnya (2 kasus K9, 6 TP, 30 node normal, observer tanpa b terukur sintetis,
tabrakan sintetis) tetap lolos.

---

## 11. Keputusan final dan pembekuan langkah 3

### 11.1 Keputusan reviewer

| Butir | Keputusan |
|---|---|
| Status langkah 3 | **Diterima dan dibekukan** sebagai bagian reproduksi |
| Metode utama (primary reproduction baseline) | **Pra-K9**: estimator drop terkoreksi langkah 2 apa adanya, tanpa pengecualian observer (`--b-max 0`, tercatat `b_max_observer: null`) |
| K9 (b_max = 0.8) | **Varian pembanding eksperimental**, bukan metode utama |
| N(1 − b) (10.9.4 butir 3) | **Ditunda**, tidak diimplementasikan |
| Optimasi atau perubahan algoritma DTO | Tidak ada lagi di langkah 3 |

Tidak ada perubahan kode untuk keputusan ini. Default kode (`B_MAX_OBSERVER = 0.8` di
`ml/dto_detect.py`) dan driver `ml/run_dto_step3.py` tetap seperti commit `575e7a2`.
Karena itu metode utama harus dijalankan dengan `--b-max 0` secara eksplisit (11.2).
Keluaran yang di-commit di `ns3-sim/results/step3/` dan `ml/reports/dto_step3_*.json`
adalah keluaran **varian K9**; keluaran metode utama dibuat ulang dengan command di
bawah (deterministik).

### 11.2 Konfigurasi dan command

Konfigurasi bersama (K5, konfigurasi reproduksi, bukan nilai paper): m = 30, Y = 100,
N_min = 10, δ = 0.1, α = 0.01, dto_seed = 0, energi Not Available (K3/K10). Satu-satunya
beda antara kedua metode adalah `--b-max`.

**Metode utama (pra-K9)**, dari folder `ml/`, contoh untuk stage2 (grup utama K7):

```bash
../.venv/bin/python dto_detect.py --telem-dir ../ns3-sim/results/step2/telemetry_stage2 \
  --run-tag stage2 --out-dir ../ns3-sim/results/step3_primary/stage2 \
  --nodes 20 30 40 50 60 70 80 90 100 --seeds 1 2 3 --b-max 0
../.venv/bin/python dto_eval.py --dec-dir ../ns3-sim/results/step3_primary/stage2 \
  --run stage2 --variants main skip paper_k tx_ablation --wtag all \
  --nodes 20 30 40 50 60 70 80 90 100 --seeds 1 2 3 \
  --scenario-dir ../ns3-sim/results --telem-dir ../ns3-sim/results/step2/telemetry_stage2 \
  --metrics-dir ../ns3-sim/results/step2 --metrics-tag _stage2 \
  --out ../ns3-sim/results/step3_primary/eval_stage2.json
```

- ctrl0: ganti `stage2` dengan `ctrl0` dan `--nodes 20 60 100`.
- stage1 (sekunder): ganti `stage2` dengan `stage1`.
- Window 0: tambahkan `--variants main --windows 0` pada `dto_detect.py` dan
  `--variants main --wtag w0` pada `dto_eval.py`.
- `step3_primary/` adalah contoh folder keluaran; tidak di-commit.

**Varian pembanding K9:** `.venv/bin/python ml/run_dto_step3.py` (default
`b_max = 0.8`). Ini menghasilkan semua grup (stage2, stage2 w0, ctrl0, stage1,
stage1rep, seed DTO 1–4, (m, Y)) ke `ns3-sim/results/step3/` dan `ml/reports/`.
Varian ini juga bisa dijalankan dengan command di atas tanpa `--b-max 0`.

### 11.3 Verifikasi `--b-max 0` = pra-K9

- **Unit:** `test_disabled_equals_step2_estimator` (N dan D identik dengan
  `corrected_trust`). **Telemetry nyata:**
  `test_estimator_without_exclusion_equals_step2_on_real_telemetry` (126 kasus).
- **Ujung ke ujung (dijalankan saat pembekuan):** command 11.2 menghasilkan angka pool
  yang identik dengan tabel pra-K9 di 10.5:

| Run / varian | TP | FP | FN | Precision | Recall | FPR | Recall (berbukti) | Cakupan | argmax |
|---|---|---|---|---|---|---|---|---|---|
| **stage2 / main** | 33 | 0 | 129 | 1.000 | 0.204 | 0.000 | 0.971 | 34/162 | 60/60 |
| stage2 / skip | 33 | 0 | 129 | 1.000 | 0.204 | 0.000 | 0.971 | 34/162 | 577/577 |
| stage2 / paper_k | 33 | 129 | 129 | 0.204 | 0.204 | 0.088 | 0.971 | 34/162 | 189/189 |
| stage2 / tx_ablation | 101 | 442 | 61 | 0.186 | 0.623 | 0.303 | 0.623 | 162/162 | 566/570 |
| stage2 / main, window 0 | 33 | 0 | 129 | 1.000 | 0.204 | 0.000 | 0.971 | 34/162 | 60/60 |
| **ctrl0 / main** | 0 | 0 | 54 | – | 0.000 | 0.000 | 0.000 | 24/54 | 9/9 |
| ctrl0 / paper_k | 6 | 48 | 48 | 0.111 | 0.111 | 0.099 | 0.250 | 24/54 | 63/63 |
| ctrl0 / tx_ablation | 29 | 156 | 25 | 0.157 | 0.537 | 0.321 | 0.537 | 54/54 | 193/194 |
| stage1 / main (sekunder) | 71 | 0 | 91 | 1.000 | 0.438 | 0.000 | 1.000 | 71/162 | 98/98 |
| stage1 / paper_k | 71 | 91 | 91 | 0.438 | 0.438 | 0.062 | 1.000 | 71/162 | 189/189 |
| stage1 / tx_ablation | 89 | 385 | 73 | 0.188 | 0.549 | 0.264 | 0.549 | 162/162 | 496/501 |

Baris ctrl0 / tx_ablation, stage1 / paper_k, dan stage1 / tx_ablation pra-K9 belum ada di
10.5; angkanya berasal dari verifikasi ini. Determinisme, stabilitas seed DTO, dan
sensitivitas (m, Y) untuk metode utama tercatat di 10.6 (diukur pra-K9: 3/3, 27/27 × 4,
27/27). Saat pembekuan, ketiganya tidak diukur ulang dengan `--b-max 0`.

### 11.4 Keterbatasan yang dibekukan bersama metode

**Metode utama (pra-K9):**

- Recall rendah karena cakupan: stage2 hanya 34/162 malicious pernah teramati sebagai
  relay. Flooding tidak terdeteksi karena energi Not Available (K3/K10).
- Tidak lebih baik dari ambang trust telemetry sederhana (stage2 33 vs 32 TP, keduanya
  0 FP). DTO ≈ argmax (K1).
- **FN berbukti karena observer b tinggi:** stage2 n=80 s=2 node 3 diputuskan `normal`
  (N = 50, D = 0), karena semua drop jatuh ke kategori ambigu di observer b = 0.941
  (10.6 butir 8, 10.9.2).
- **Kepastian berlebihan pada observer b tinggi:** sebagian TP bergantung pada cabang
  b = 1 (`D = A + U`) atau penguatan `U/(1 − b)` dengan U kecil (10.9.2). Keputusannya
  benar menurut audit, tetapi kepastian posteriornya tidak terjamin.
- Aturan berhenti tidak monoton (10.6 butir 9); pada data ini `skip` = `main`.
- `paper_k` (k = 10% a priori) merusak precision; hanya pembanding.

**Varian pembanding K9:**

- Menghilangkan FN berbukti di atas, tetapi kehilangan 6 TP (2 stage2, 4 stage1) dan
  menjadikan 30 node normal `insufficient_evidence` (10.8).
- Recall stage2 0.191, di bawah ambang trust sederhana (0.198).
- b mencakup tabrakan di sekitar observer, sehingga observer di area padat lebih mungkin
  dikecualikan (10.8).
- Sensitivitas (m, Y) = (10, 30) 26/27 (10.8).
- Kandidat "pertahankan bukti positif" ditolak (10.9.3).

**Belum dikerjakan (ditunda):** N(1 − b); pemulihan kriteria energi dan pemisahan
kegagalan frame penerusan (c) memerlukan perubahan telemetry (langkah 4–5); integrasi
online DTO ke NS-3 (langkah 4–5).
