"""Uji DTO langkah 3: persamaan (21)-(31), optimizer, deteksi, isolasi label."""
import inspect
import os
import re
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import dto as DT                       # noqa: E402
import dto_detect as DD                # noqa: E402
import telemetry_schema as S           # noqa: E402


class TestEquations(unittest.TestCase):
    def setUp(self):
        self.opt = DT.DTO(DT.DTOConfig(m=10, Y=50, seed=7), [0.0, 0.0], [10.0, 10.0])

    def test_eq24_instructor_count(self):
        self.assertEqual(DT.DTO.n_instructors(30, 1, 100), 2)      # floor(0.1*30*0.99)=2
        self.assertEqual(DT.DTO.n_instructors(30, 60, 100), 1)     # floor(1.2)=1
        self.assertEqual(DT.DTO.n_instructors(30, 100, 100), 1)    # rumus = 0 -> minimal 1
        self.assertEqual(DT.DTO.n_instructors(100, 0, 100), 10)

    def test_eq29_patterning_index(self):
        self.assertAlmostEqual(DT.DTO.patterning_index(0, 100), 0.91)
        self.assertAlmostEqual(DT.DTO.patterning_index(100, 100), 0.01)
        self.assertAlmostEqual(DT.DTO.patterning_index(50, 100), 0.01 + 0.45)

    def test_eq25_phase1_both_branches(self):
        z, idk = np.array([4.0, 2.0]), np.array([1.0, 3.0])
        rng = np.random.default_rng(123)
        self.opt.rng = np.random.default_rng(123)
        r, r1 = rng.random(2), 1.0 + rng.random(2)
        np.testing.assert_allclose(self.opt.phase1(z, idk, of_idk=0.0, of_i=1.0),
                                   z + r * (idk - r1 * z))           # instruktur lebih baik
        rng = np.random.default_rng(5)
        self.opt.rng = np.random.default_rng(5)
        r = rng.random(2)
        np.testing.assert_allclose(self.opt.phase1(z, idk, of_idk=2.0, of_i=1.0),
                                   z + r * (z - idk))                # instruktur lebih buruk

    def test_eq27_phase2(self):
        z, idk = np.array([4.0, 2.0]), np.array([1.0, 3.0])
        np.testing.assert_allclose(DT.DTO.phase2(z, idk, 0.3), 0.3 * z + 0.7 * idk)

    def test_eq30_phase3(self):
        z = np.array([4.0, 2.0])
        rng = np.random.default_rng(9)
        self.opt.rng = np.random.default_rng(9)
        r = rng.random(2)
        np.testing.assert_allclose(self.opt.phase3(z, 25, 100), z + (1 - 2 * r) * 0.75 * z)
        self.assertTrue(np.allclose(self.opt.phase3(z, 100, 100), z))   # amplitudo 0 di q = Y


class TestOptimizer(unittest.TestCase):
    def test_greedy_best_monotone_and_bounds(self):
        seen = []

        def f(x):
            seen.append(x.copy())
            return float(np.sum((x - 3.3) ** 2))
        r = DT.DTO(DT.DTOConfig(m=20, Y=40, seed=1), [-5, -5, -5], [5, 5, 5]).minimize(f)
        best = [h[3] for h in r.history]
        self.assertTrue(all(b2 <= b1 for b1, b2 in zip(best, best[1:])))
        X = np.array(seen)
        self.assertTrue(np.all(X >= -5) and np.all(X < 5))
        self.assertEqual(r.n_eval, 20 + 40 * 20 * 3)

    def test_sanity_sphere_and_rastrigin(self):
        sph = DT.DTO(DT.DTOConfig(m=30, Y=200, seed=2), [-10] * 5, [10] * 5).minimize(
            lambda x: float(np.sum(x ** 2)))
        self.assertLess(sph.f_best, 1e-3)

        def ras(x):
            return float(10 * len(x) + np.sum(x ** 2 - 10 * np.cos(2 * np.pi * x)))
        rr = DT.DTO(DT.DTOConfig(m=30, Y=200, seed=3), [-5.12] * 5, [5.12] * 5).minimize(ras)
        self.assertLess(rr.f_best, ras(np.full(5, 2.5)))   # jauh lebih baik dari titik acak

    def test_deterministic(self):
        def f(x):
            return float(np.sum(np.abs(x - 1)))
        a = DT.DTO(DT.DTOConfig(m=10, Y=20, seed=4), [0, 0], [5, 5]).minimize(f)
        b = DT.DTO(DT.DTOConfig(m=10, Y=20, seed=4), [0, 0], [5, 5]).minimize(f)
        np.testing.assert_array_equal(a.x_best, b.x_best)

    def test_finds_argmax_on_node_encoding(self):
        rng = np.random.default_rng(0)
        hits = 0
        for t in range(30):
            S = rng.random(int(rng.integers(5, 100)))
            r = DT.DTO(DT.DTOConfig(m=30, Y=100, seed=t), [1.0], [len(S) + 1.0]).minimize(
                lambda z: -S[int(np.floor(z[0] - 1.0))])
            hits += int(np.floor(r.x_best[0] - 1.0)) == int(np.argmax(S))
        self.assertEqual(hits, 30)


def _links(n, observers, relays, drop, heard_rxfail=0, tx=50, extra_tx=None):
    """Baris telemetry_links sintetis: tiap relay j diamati oleh beberapa observer."""
    rows = []
    for j in range(n):
        for i in observers.get(j, []):
            w = relays.get(j, 0)
            d = int(round(drop.get(j, 0.0) * w))
            r = {c: 0 for c in S.LINK_COLUMNS}
            r.update(window=0, observer=i, neighbor_type="sensor", neighbor_id=j,
                     wd_started=w, wd_forwarded=w - d, wd_unobserved_clean=d,
                     wd_heard_rxfail=heard_rxfail,
                     rx_ok_from=(extra_tx or {}).get(j, tx), rssi_mean_dbm=-14.0)
            rows.append(r)
    return rows


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.n = 20
        self.obs = {j: [(j + 1) % 20, (j + 2) % 20] for j in range(20)}
        self.relay = {j: 40 for j in range(12)}          # 12 relay teramati, 8 tidak

    def test_grayhole_relays_detected_no_labels(self):
        drop = {3: 0.7, 7: 0.7}
        ev = DD.evidence(_links(self.n, self.obs, self.relay, drop), self.n)
        rows, info = DD.detect(ev, self.n, "main", seed=1)
        mal = {r["node_id"] for r in rows if r["decision"] == "malicious"}
        self.assertEqual(mal, {3, 7})
        self.assertTrue(all(st["dto_found_argmax"] for st in info["steps"]))
        ins = {r["node_id"] for r in rows if r["decision"] == "insufficient_evidence"}
        self.assertEqual(ins, set(range(12, 20)))       # bukan relay -> tidak diputuskan

    def test_no_attack_no_detection(self):
        ev = DD.evidence(_links(self.n, self.obs, self.relay, {}), self.n)
        for v in ("main", "skip"):
            rows, _ = DD.detect(ev, self.n, v, seed=1)
            self.assertEqual(sum(r["decision"] == "malicious" for r in rows), 0, v)

    def test_paper_k_isolates_exactly_k(self):
        ev = DD.evidence(_links(self.n, self.obs, self.relay, {3: 0.7}), self.n)
        rows, _ = DD.detect(ev, self.n, "paper_k", seed=1)
        self.assertEqual(sum(r["decision"] == "malicious" for r in rows), 2)   # ceil(0.1*20)

    def test_tx_ablation_flags_flooder_without_relay_evidence(self):
        tx = {j: 40 + 2 * j for j in range(self.n)}      # variasi alami
        tx[15] = 900                                     # flooder, bukan relay
        ev = DD.evidence(_links(self.n, self.obs, self.relay, {}, extra_tx=tx), self.n)
        rows, _ = DD.detect(ev, self.n, "tx_ablation", seed=1)
        self.assertIn(15, {r["node_id"] for r in rows if r["decision"] == "malicious"})

    def test_robust_z_zero_mad_is_neutral(self):
        # MAD = 0 -> semua z = 0 (uji TX tidak menandai siapa pun; perilaku terdokumentasi)
        np.testing.assert_array_equal(DD.robust_z(np.array([5.0, 5.0, 5.0, 9.0])), 0.0)

    def test_deterministic_and_seed_robust(self):
        ev = DD.evidence(_links(self.n, self.obs, self.relay, {3: 0.7, 7: 0.6}), self.n)
        a = DD.detect(ev, self.n, "main", seed=11)[0]
        b = DD.detect(ev, self.n, "main", seed=11)[0]
        c = DD.detect(ev, self.n, "main", seed=99)[0]
        self.assertEqual(a, b)
        self.assertEqual([r["decision"] for r in a], [r["decision"] for r in c])

    def test_non_whitelisted_columns_do_not_matter(self):
        links = _links(self.n, self.obs, self.relay, {3: 0.7})
        base = DD.detect(DD.evidence(links, self.n), self.n, "tx_ablation", seed=1)[0]
        mod = [dict(r) for r in links]
        for r in mod:
            for c in S.LINK_COLUMNS:
                if c not in S.DTO_INPUT_LINK_COLUMNS and c != "neighbor_type":
                    r[c] = 777
        self.assertEqual(DD.detect(DD.evidence(mod, self.n), self.n, "tx_ablation", seed=1)[0],
                         base)


def _watch(i, j, F=0, A=0, U=0, heard_rxfail=0):
    r = {c: 0 for c in S.LINK_COLUMNS}
    r.update(window=0, observer=i, neighbor_type="sensor", neighbor_id=j, wd_started=F + A + U,
             wd_forwarded=F, wd_unobserved_rxfail=A, wd_unobserved_clean=U,
             wd_heard_rxfail=heard_rxfail, rx_ok_from=F + 5, rssi_mean_dbm=-14.0)
    return r


class TestK9ObserverExclusion(unittest.TestCase):
    """K9: observer dgn b_i >= 0.8 tidak memberi bukti untuk N_j."""

    def _scenario(self, relay_drop=0):
        n = 12
        rows = []
        # observer 9: b = 47/50 = 0.94; semua 50 watch ke node 3 (grayhole) jatuh ke ambigu
        rows.append(_watch(9, 0, F=50, heard_rxfail=47))
        rows.append(_watch(9, 3, A=50))
        # observer 10, 11: andal (b = 0); relay normal 1, 2 dan relay grayhole 4
        for i in (10, 11):
            rows += [_watch(i, 1, F=40), _watch(i, 2, F=40),
                     _watch(i, 4, F=40 - relay_drop, U=relay_drop)]
        return n, rows

    def test_uninformative_observer_gives_insufficient_evidence_not_normal(self):
        n, rows = self._scenario(relay_drop=28)
        pre = DD.detect(DD.evidence(rows, n, b_max=None), n, "main", seed=1)[0]
        post_ev = DD.evidence(rows, n)
        post = DD.detect(post_ev, n, "main", seed=1)[0]
        self.assertEqual(pre[3]["decision"], "normal")             # kegagalan pra-K9 (D = 0)
        self.assertEqual(post[3]["decision"], "insufficient_evidence")
        self.assertEqual(post[3]["n_watched_excluded"], "50")
        self.assertEqual(post_ev["excluded_observers"], {9: 0.94})
        # target dgn observer andal tidak terpengaruh
        for j in (1, 2, 4):
            self.assertEqual(pre[j]["decision"], post[j]["decision"], j)
        self.assertEqual(post[4]["decision"], "malicious")
        # observer yg dikecualikan tetap tidak dipakai di target lain: N_0 = 0
        self.assertEqual(post_ev["N"][0], 0)

    def test_b_is_observer_failure_not_network_loss(self):
        # menambah drop (packet loss jaringan) pada relay tidak mengubah b observer
        n, r0 = self._scenario(relay_drop=0)
        _, r1 = self._scenario(relay_drop=35)
        b0, _ = DD.coincidence_rates(r0)
        b1, _ = DD.coincidence_rates(r1)
        self.assertEqual(b0, b1)
        self.assertEqual(DD.evidence(r0, n)["excluded_observers"],
                         DD.evidence(r1, n)["excluded_observers"])
        # b hanya dari watch terdengar: drop (A/U) tidak masuk pembilang maupun penyebut
        self.assertEqual(b1[10], 0.0)

    def test_threshold_boundary(self):
        n = 6
        rows = [_watch(4, 0, F=100, heard_rxfail=80), _watch(5, 0, F=100, heard_rxfail=79),
                _watch(4, 1, F=20, heard_rxfail=16), _watch(5, 2, F=20, heard_rxfail=16)]
        ev = DD.evidence(rows, n)
        # b_4 = 96/120 = 0.80 (dikecualikan), b_5 = 95/120 = 0.79 (dipakai)
        self.assertEqual(set(ev["excluded_observers"]), {4})
        self.assertEqual((ev["N"][1], ev["N"][2]), (0, 20))

    def test_disabled_equals_step2_estimator(self):
        from telemetry_trust import corrected_trust
        n, rows = self._scenario(relay_drop=28)
        ct = corrected_trust(rows, n)
        ev = DD.evidence(rows, n, b_max=None)
        np.testing.assert_array_equal(ev["N"], ct["n_watched"])
        np.testing.assert_array_equal(ev["D"], ct["drops_est"])
        # tanpa observer yang melewati ambang -> estimator K9 identik dgn langkah 2
        ev2 = DD.evidence(rows, n, b_max=0.99)
        np.testing.assert_array_equal(ev2["N"], ct["n_watched"])
        np.testing.assert_allclose(ev2["D"], ct["drops_est"], rtol=0, atol=1e-12)

    def test_unmeasured_observer_never_excluded(self):
        # observer 3 tanpa watch terdengar -> b = b gabungan (tinggi), tetapi tidak terukur
        n = 6
        rows = [_watch(4, 0, F=10, heard_rxfail=9), _watch(3, 1, U=20)]
        ev = DD.evidence(rows, n)
        self.assertEqual(set(ev["excluded_observers"]), {4})
        self.assertEqual(ev["N"][1], 20)

    def test_collision_driven_b_excludes_dense_observer(self):
        # b adalah kegagalan terima PHY observer, TERMASUK tabrakan dari pemancar lain:
        # observer di area padat (banyak rxfail saat penerusan terdengar) ikut dikecualikan
        # walau target-nya jujur. Ini konsekuensi terdokumentasi (10.8), bukan bug.
        n = 6
        rows = [_watch(4, 0, F=50, heard_rxfail=45), _watch(5, 1, F=50, heard_rxfail=5)]
        ev = DD.evidence(rows, n)
        self.assertEqual((ev["N"][0], ev["N"][1]), (0, 50))
        rows_, _ = DD.detect(ev, n, "main", seed=1)
        self.assertEqual(rows_[0]["decision"], "insufficient_evidence")
        self.assertEqual(rows_[1]["decision"], "normal")

    def test_step2_trust_unchanged(self):
        # K9 hanya di DTO: corrected_trust (trust/routing langkah 2) tetap memakai observer 9
        from telemetry_trust import corrected_trust
        n, rows = self._scenario(relay_drop=28)
        self.assertEqual(corrected_trust(rows, n)["n_watched"][3], 50)


RES = os.path.join(HERE, "..", "..", "ns3-sim", "results")
S2 = os.path.join(RES, "step2")


_K9_RUNS = ("stage2", "ctrl0", "stage1")


@unittest.skipUnless(all(os.path.isdir(os.path.join(S2, f"telemetry_{t}")) for t in _K9_RUNS),
                     "telemetry langkah 2 (stage2/ctrl0/stage1) tidak lengkap")
class TestK9OnStep2Telemetry(unittest.TestCase):
    """Dampak K9 pada telemetry NS-3 langkah 2 (varian main, stage2 + ctrl0 + stage1).
    Label dibaca HANYA di sini, untuk evaluasi, setelah keputusan dibuat. Angka yang
    dipatok = hasil terukur, tidak dipaksakan.

    Definisi "terdampak" (dinyatakan eksplisit, lihat STEP3_DTO_DESIGN.md 10.8):
      - malicious terdampak = node malicious yang keputusannya berubah karena K9. Ada dua
        jenis: (a) 2 node berbukti yg pra-K9 `normal` -> `insufficient_evidence`
        (kasus sasaran K9), dan (b) 6 TP `malicious` -> `insufficient_evidence` (efek
        samping). Keduanya dipatok di bawah.
      - normal terdampak = node normal yang berubah ke / dari `malicious`: 0. Selain itu
        30 node normal berubah `normal` -> `insufficient_evidence` (tidak mengubah TN/FPR),
        juga dipatok di bawah."""

    @classmethod
    def setUpClass(cls):
        from dto_eval import labels
        from telemetry_trust import corrected_trust
        nodes = [20, 30, 40, 50, 60, 70, 80, 90, 100]
        cls.trans = {}
        cls.step2_mismatch = []
        cls.checked = 0
        for tag, ns in zip(_K9_RUNS, (nodes, [20, 60, 100], nodes)):
            for n in ns:
                for s in (1, 2, 3):
                    links = S.load_links(S.paths(os.path.join(S2, f"telemetry_{tag}"), n, s)["links"])
                    e0 = DD.evidence(links, n, b_max=None)
                    e1 = DD.evidence(links, n)
                    # estimator K9 tanpa observer dikecualikan == corrected_trust langkah 2
                    for w in (None, {0}):
                        view = S.trust_view(links, S.DTO_INPUT_LINK_COLUMNS)
                        b, pooled = DD.coincidence_rates(view, w)
                        Nk, Dk, Nx = DD._corrected_excluding(view, n, w, b, pooled, {})
                        ct = corrected_trust(links, n, w)
                        cls.checked += 1
                        if not (np.array_equal(Nk, ct["n_watched"]) and not Nx.any()
                                and np.allclose(Dk, ct["drops_est"], rtol=0, atol=1e-9)):
                            cls.step2_mismatch.append((tag, n, s, w))
                    if np.array_equal(e0["N"], e1["N"]) and np.array_equal(e0["D"], e1["D"]):
                        continue                     # bukti identik -> keputusan identik
                    seed = n * 101 + s * 7
                    d0 = [r["decision"] for r in DD.detect(e0, n, "main", seed=seed)[0]]
                    d1 = [r["decision"] for r in DD.detect(e1, n, "main", seed=seed)[0]]
                    mal, _ = labels(RES, n, s)
                    for j in range(n):
                        if d0[j] != d1[j]:
                            k = ("mal" if mal[j] else "nor", d0[j], d1[j])
                            cls.trans.setdefault(k, []).append((tag, n, s, j))

    def test_estimator_without_exclusion_equals_step2_on_real_telemetry(self):
        self.assertEqual(self.checked, 126)              # 63 run x (semua window, window 0)
        self.assertEqual(self.step2_mismatch, [])

    def test_two_malicious_evidenced_normal_become_insufficient_evidence(self):
        # (a) kasus sasaran K9. stage2 n=80 s=2 node 3 = FN berbukti grayhole (10.6 butir 8);
        # ctrl0 n=100 s=1 node 32 = malicious di kontrol TANPA grayhole (tidak men-drop),
        # dihitung FN hanya pada metrik berlabel.
        got = sorted(self.trans.get(("mal", "normal", "insufficient_evidence"), []))
        self.assertEqual(got, [("ctrl0", 100, 1, 32), ("stage2", 80, 2, 3)])

    def test_no_normal_node_gains_or_loses_malicious_label(self):
        changed = [k for k in self.trans if k[0] == "nor" and "malicious" in k[1:]]
        self.assertEqual(changed, [])
        # tidak ada node yg berpindah ke "normal" karena K9
        self.assertFalse([k for k in self.trans if k[2] == "normal"])

    def test_side_effects_are_reported_not_hidden(self):
        # (b) efek samping terukur (STEP3_DTO_DESIGN.md 10.8):
        # TP yang hilang karena bukti drop nyata berasal dari observer b >= 0.8
        lost = sorted(self.trans.get(("mal", "malicious", "insufficient_evidence"), []))
        self.assertEqual(lost, [("stage1", 70, 2, 17), ("stage1", 70, 3, 5), ("stage1", 80, 2, 3),
                                ("stage1", 100, 1, 32), ("stage2", 70, 3, 5), ("stage2", 90, 3, 3)])
        # node normal normal -> insufficient_evidence (stage2 9, ctrl0 6, stage1 15)
        cov = self.trans.get(("nor", "normal", "insufficient_evidence"), [])
        per = {t: sum(1 for x in cov if x[0] == t) for t in _K9_RUNS}
        self.assertEqual(per, {"stage2": 9, "ctrl0": 6, "stage1": 15})
        # tidak ada jenis transisi lain
        self.assertEqual(set(self.trans), {("mal", "normal", "insufficient_evidence"),
                                           ("mal", "malicious", "insufficient_evidence"),
                                           ("nor", "normal", "insufficient_evidence")})


def _positive_only_evidence(links, n, b_max=0.8):
    """KANDIDAT YANG DITOLAK (tinjauan K9, STEP3_DTO_DESIGN.md 10.9), hanya untuk uji;
    tidak dipakai DTO. Observer dgn b terukur >= b_max hanya menyumbang watch tak-ambigu
    (F terdengar, U clean): N += F + U, D += U; kategori ambigu A dibuang. Observer lain
    seperti langkah 2."""
    import collections
    view = S.trust_view(links, S.DTO_INPUT_LINK_COLUMNS)
    b, pooled = DD.coincidence_rates(view)
    heard = collections.Counter()
    for r in view:
        if r["neighbor_type"] == "sensor":
            heard[r["observer"]] += r["wd_forwarded"] + r["wd_forwarded_late"]
    bad = {i for i, v in b.items() if heard[i] > 0 and v >= b_max}
    N, A, U, D = (np.zeros(n) for _ in range(4))
    for r in view:
        if r["neighbor_type"] != "sensor":
            continue
        i, j = r["observer"], r["neighbor_id"]
        F = r["wd_forwarded"] + r["wd_forwarded_late"]
        a, u = r["wd_unobserved_rxfail"], r["wd_unobserved_clean"]
        if i in bad:
            N[j] += F + u
            U[j] += u
            D[j] += u
            continue
        bi = b.get(i, pooled)
        N[j] += F + a + u
        A[j] += a
        U[j] += u
        D[j] += (a + u) if bi >= 1.0 else u / (1.0 - bi)
    D = np.minimum(D, A + U)
    ev = DD.evidence(links, n, b_max=None)
    ev.update(N=N, D=D, plr=np.where(N > 0, D / np.maximum(N, 1e-12), np.nan))
    return ev


class TestK9PositiveEvidenceReview(unittest.TestCase):
    """Tinjauan K9 (sintetis): mengapa bukti positif saja dari observer b tinggi bias."""

    def test_positive_only_understates_plr_when_drops_hide_in_ambiguous(self):
        # observer tabrakan-berat b = 0.9 (diukur pada 30 penerusan terdengar); target
        # grayhole q = 0.7 atas 100 paket: 70 drop -> 63 ambigu (A) + 7 clean (U),
        # 30 penerusan -> terdengar (F). Drop tersembunyi di A dgn peluang b, penerusan tidak.
        n = 4
        rows = [_watch(3, 0, F=30, A=63, U=7, heard_rxfail=27)]
        pos = _positive_only_evidence(rows, n)
        self.assertAlmostEqual(pos["plr"][0], 7 / 37)              # 0.19, kebenaran 0.7
        self.assertEqual(pos["N"][0], 37)                          # >= N_min -> diputuskan
        self.assertEqual(DD.detect(pos, n, "main", seed=1)[0][0]["decision"], "normal")
        # K9 (berlaku): tidak memutuskan
        k9 = DD.detect(DD.evidence(rows, n), n, "main", seed=1)[0][0]["decision"]
        self.assertEqual(k9, "insufficient_evidence")
        # pra-K9: benar di sini HANYA karena U = 7 diperkuat 10x (D = 70)
        pre = DD.evidence(rows, n, b_max=None)
        self.assertAlmostEqual(pre["D"][0], 70.0)

    def test_same_mechanism_gives_fn_when_clean_count_is_zero(self):
        # pola stage2 n=80 s=2 node 3: semua drop jatuh ke A, U = 0 -> pra-K9 D = 0
        n = 4
        rows = [_watch(3, 0, F=17, A=33, U=0, heard_rxfail=16)]
        pre = DD.evidence(rows, n, b_max=None)
        self.assertEqual(pre["D"][0], 0.0)
        self.assertEqual(DD.detect(_positive_only_evidence(rows, n), n, "main", seed=1)[0][0]
                         ["decision"], "normal")                    # kandidat juga gagal


_CASES_K9 = [("stage2", 80, 2, 3), ("ctrl0", 100, 1, 32)]
_CASES_TP = [("stage2", 70, 3, 5), ("stage2", 90, 3, 3), ("stage1", 70, 2, 17),
             ("stage1", 70, 3, 5), ("stage1", 80, 2, 3), ("stage1", 100, 1, 32)]


@unittest.skipUnless(all(os.path.isdir(os.path.join(S2, f"telemetry_{t}")) for t in _K9_RUNS),
                     "telemetry langkah 2 (stage2/ctrl0/stage1) tidak lengkap")
class TestK9PositiveEvidenceOnTelemetry(unittest.TestCase):
    """Tinjauan K9 pada telemetry nyata. Label hanya untuk evaluasi, setelah keputusan."""

    @classmethod
    def setUpClass(cls):
        import collections
        from dto_eval import labels
        nodes = [20, 30, 40, 50, 60, 70, 80, 90, 100]
        cls.cand = {}                 # transisi pra-K9 -> kandidat bukti-positif
        cls.cand_fp = 0
        cls.watchless_unmeasured = cls.unmeasured_with_watches = 0
        cls.excl_b_ok = True
        cls.case = {}
        want = set(_CASES_K9 + _CASES_TP)
        for tag, ns in zip(_K9_RUNS, (nodes, [20, 60, 100], nodes)):
            for n in ns:
                for s in (1, 2, 3):
                    links = S.load_links(S.paths(os.path.join(S2, f"telemetry_{tag}"), n, s)["links"])
                    view = S.trust_view(links, S.DTO_INPUT_LINK_COLUMNS)
                    b, _ = DD.coincidence_rates(view)
                    heard, hrx, watches = (collections.Counter() for _ in range(3))
                    per = collections.defaultdict(lambda: [0, 0, 0])
                    for r in view:
                        if r["neighbor_type"] != "sensor":
                            continue
                        i, F = r["observer"], r["wd_forwarded"] + r["wd_forwarded_late"]
                        a, u = r["wd_unobserved_rxfail"], r["wd_unobserved_clean"]
                        heard[i] += F
                        hrx[i] += r["wd_heard_rxfail"]
                        watches[i] += F + a + u
                        p = per[(i, r["neighbor_id"])]
                        p[0] += F
                        p[1] += a
                        p[2] += u
                    for i in watches:
                        if heard[i] == 0:
                            cls.watchless_unmeasured += watches[i] == 0
                            cls.unmeasured_with_watches += watches[i] > 0
                    e1 = DD.evidence(links, n)
                    for i, v in e1["excluded_observers"].items():   # b hanya dari watch terdengar
                        cls.excl_b_ok &= heard[i] > 0 and abs(v - hrx[i] / heard[i]) < 1e-12
                    for (t, nn, ss, j) in want:
                        if (t, nn, ss) == (tag, n, s):
                            cls.case[(t, nn, ss, j)] = {
                                i: (F, A, U, b[i]) for (i, jj), (F, A, U) in per.items()
                                if jj == j and F + A + U > 0}
                    e0 = DD.evidence(links, n, b_max=None)
                    ep = _positive_only_evidence(links, n)
                    if np.array_equal(e0["N"], ep["N"]) and np.array_equal(e0["D"], ep["D"]):
                        continue
                    seed = n * 101 + s * 7
                    d0 = [r["decision"] for r in DD.detect(e0, n, "main", seed=seed)[0]]
                    dp = [r["decision"] for r in DD.detect(ep, n, "main", seed=seed)[0]]
                    mal, _ = labels(RES, n, s)
                    cls.cand_fp += sum(1 for j in range(n) if dp[j] == "malicious" and not mal[j])
                    for j in range(n):
                        if d0[j] != dp[j]:
                            k = ("mal" if mal[j] else "nor", d0[j], dp[j])
                            cls.cand.setdefault(k, []).append((tag, n, s, j))

    def test_six_lost_tps_relied_on_ambiguous_watches(self):
        # Bukti yang membuat 6 TP terdeteksi pra-K9 berasal dari kategori ambigu A, lewat
        # cabang b = 1 (D = A + U) atau penguatan U/(1 - b) dgn U kecil, BUKAN bukti positif.
        for key in _CASES_TP:
            obs = self.case[key]
            self.assertTrue(all(b >= 0.8 for (_, _, _, b) in obs.values()), key)
            A = sum(o[1] for o in obs.values())
            U = sum(o[2] for o in obs.values())
            self.assertGreater(A, U, key)          # terukur: A/(A+U) min 0.73 (8 vs 3)
            for F, a, u, b in obs.values():
                self.assertTrue(b >= 1.0 or u <= 7, (key, u, b))

    def test_two_k9_cases_have_no_clean_drop_observation(self):
        for key in _CASES_K9:
            obs = self.case[key]
            self.assertEqual(len(obs), 1, key)
            (F, A, U, b), = obs.values()
            self.assertEqual(U, 0, key)
            self.assertGreaterEqual(b, 0.8, key)

    def test_positive_only_candidate_recovers_no_tp_and_turns_them_normal(self):
        # kandidat vs pra-K9: satu-satunya perubahan = 6 TP -> "normal" (FN berbukti baru)
        self.assertEqual(set(self.cand), {("mal", "malicious", "normal")})
        self.assertEqual(sorted(self.cand[("mal", "malicious", "normal")]), sorted(_CASES_TP))
        self.assertEqual(self.cand_fp, 0)

    def test_positive_only_candidate_keeps_k9_targets_normal(self):
        # 2 kasus K9 tetap "normal" (seperti pra-K9) pada kandidat: tidak ada di self.cand
        flat = {x for v in self.cand.values() for x in v}
        for key in _CASES_K9:
            self.assertNotIn(key, flat)

    def test_unmeasured_observers_never_contribute_watches(self):
        # di data nyata, observer tanpa watch terdengar tidak punya watch sama sekali
        self.assertEqual(self.unmeasured_with_watches, 0)
        self.assertEqual(self.watchless_unmeasured, 1268)

    def test_excluded_observer_b_is_measured_on_heard_watches(self):
        self.assertTrue(self.excl_b_ok)


class TestLabelIsolation(unittest.TestCase):
    def test_detector_source_reads_no_labels_or_self_columns(self):
        src = inspect.getsource(DD) + inspect.getsource(DT)
        code = re.sub(r'"""(.|\n)*?"""', "", src)
        code = re.sub(r"#[^\n]*", "", code)
        for tok in ("bigan_decisions", "actual_mal", "watchdog_audit", "load_audit",
                    "self_", "load_nodes", "pred_intrusion"):
            self.assertNotIn(tok, code, tok)

    def test_output_columns_have_no_label(self):
        self.assertEqual(S.check_no_leakage(DD.DECISION_COLUMNS), [])


if __name__ == "__main__":
    unittest.main()
