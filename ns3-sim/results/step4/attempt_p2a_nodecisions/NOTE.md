# Pilot langkah 4, P2 percobaan a: gagal sebelum simulasi (tanpa data)

Commit server `933048b`. Folder `dec_*` (keputusan hybrid + tabel reroute) belum di-push
ke remote saat server menjalankan P2. Akibatnya run B F2 n=20 berhenti pada saat memuat
berkas, dengan `NS_FATAL_ERROR` "File keputusan hybrid tidak ditemukan:
results/step4/dec_F2/hybrid_decisions_20_s1.csv" (`log_20_s1_s4B_F2.txt`), lalu
`run_sweep.sh` berhenti.

Tidak ada data simulasi dari percobaan ini. Dipertahankan sebagai catatan. P2 dijalankan
ulang setelah `dec_*` di-push.
