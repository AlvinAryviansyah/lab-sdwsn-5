# Pilot langkah 4, percobaan 1: TIDAK SAH sebagai gerbang langkah 4

Hasil di folder ini berasal dari commit server `c757ba5` ("Pilot langkah 4: P0 + P1").
Binary dibangun dari kode langkah 3 (`7f25685`), **bukan** dari implementasi langkah 4
(`92f4cfb`), karena `92f4cfb` belum ada di remote saat server menjalankan `git pull`.

- `*_s4A*`: run A **gagal**. `--idsSource=none` tidak dikenal binary lama (lihat
  `log_20_s1_s4A.txt`). Tidak ada data run A.
- `*_s4reg*`, `*_s4tw*`: run selesai, tetapi dengan binary lama. Hasilnya hanya
  menunjukkan determinisme lingkungan server untuk kode langkah 3:
  - telemetry dan `timeseries_*` identik byte dengan `step2/*_stage2`;
  - `metrics_*` identik kecuali `rt_compute_ms` dan `computation_overhead_percent`
    (metrik waktu-dinding).

Dipertahankan sebagai catatan, bukan untuk dianalisis sebagai hasil langkah 4.
Rincian: `docs/STEP4_HYBRID_IDS_DESIGN.md` 11.6.
