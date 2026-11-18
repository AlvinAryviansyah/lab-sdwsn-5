"""Uji langkah 4: keputusan Hybrid IDS, fusi, reroute minimal, gerbang determinisme."""
import csv
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ML = os.path.join(HERE, "..")
sys.path.insert(0, ML)

import dto_detect as DD                # noqa: E402
import hybrid_eval as HE               # noqa: E402
import hybrid_ids as H                 # noqa: E402
import telemetry_schema as S           # noqa: E402

RES = os.path.join(ML, "..", "ns3-sim", "results")
CC = os.path.join(ML, "..", "ns3-sim", "honeycomb-sdwsn.cc")
MODEL = os.path.join(ML, "experiments", "phase2_tldqn", "tldqn", "checkpoints", "tldqn_seed1.pt")


def _watch(i, j, F=0, A=0, U=0, heard_rxfail=0, window=0):
    r = {c: 0 for c in S.LINK_COLUMNS}
    r.update(window=window, observer=i, neighbor_type="sensor", neighbor_id=j,
             wd_started=F + A + U, wd_forwarded=F, wd_unobserved_rxfail=A,
             wd_unobserved_clean=U, wd_heard_rxfail=heard_rxfail, rx_ok_from=F + 5,
             rssi_mean_dbm=-14.0)
    return r


def _scenario(window=0):
    """Relay 3 grayhole (70% drop), relay 1, 2, 4 jujur; 2 observer andal."""
    rows = []
    for i in (8, 9):
        rows += [_watch(i, 1, F=40, window=window), _watch(i, 2, F=40, window=window),
                 _watch(i, 4, F=40, window=window), _watch(i, 3, F=12, U=28, window=window)]
    return rows


class TestFusion(unittest.TestCase):
    def test_truth_table(self):
        exp = {
            ("F2", "malicious", 0): (True, "dto"), ("F2", "malicious", 1): (True, "dto"),
            ("F2", "normal", 0): (False, "none"), ("F2", "normal", 1): (False, "none"),
            ("F2", "insufficient_evidence", 1): (False, "none"),
            ("F1", "malicious", 0): (True, "dto"), ("F1", "malicious", 1): (True, "dto+bigan"),
            ("F1", "normal", 0): (False, "none"), ("F1", "normal", 1): (True, "bigan"),
            ("F1", "insufficient_evidence", 0): (False, "none"),
            ("F1", "insufficient_evidence", 1): (True, "bigan"),
            ("BIGAN", "malicious", 0): (False, "none"),
            ("BIGAN", "malicious", 1): (True, "bigan"),
            ("BIGAN", "normal", 0): (False, "none"),
            ("BIGAN", "normal", 1): (True, "bigan"),
            ("BIGAN", "insufficient_evidence", 0): (False, "none"),
            ("BIGAN", "insufficient_evidence", 1): (True, "bigan"),
        }
        for (f, d, b), v in exp.items():
            self.assertEqual(H.fuse(d, b, f), v, (f, d, b))

    def test_insufficient_evidence_never_isolated_by_dto(self):
        for f in H.FUSIONS:
            self.assertEqual(H.fuse("insufficient_evidence", 0, f), (False, "none"))

    def test_unknown_fusion_rejected(self):
        with self.assertRaises(ValueError):
            H.fuse("normal", 0, "F3")


class TestDecisions(unittest.TestCase):
    def setUp(self):
        self.n = 12
        self.big = np.zeros(self.n, bool)
        self.big[7] = True                          # alarm Bi-GAN pada node tanpa bukti DTO

    def test_f2_isolates_dto_only_and_f1_adds_bigan(self):
        r2, i2 = H.decide(_scenario(), self.big, self.n, 1, "F2")
        r1, i1 = H.decide(_scenario(), self.big, self.n, 1, "F1")
        rb, ib = H.decide(_scenario(), self.big, self.n, 1, "BIGAN")
        self.assertEqual(i2["isolated"], [3])
        self.assertEqual(i1["isolated"], [3, 7])
        self.assertEqual(ib["isolated"], [7])
        self.assertEqual(r2[7]["dto_decision"], "insufficient_evidence")
        self.assertEqual((r2[7]["bigan_pred"], r2[7]["isolate"]), (1, 0))   # alarm saja
        self.assertEqual((rb[3]["isolate"], rb[7]["isolate"]), (0, 1))
        self.assertEqual(i2["bigan_alarms"], 1)

    def test_only_observation_window_is_used(self):
        base = H.decide(_scenario(), self.big, self.n, 1, "F2")[0]
        late = _scenario() + [_watch(8, 1, F=1, U=60, window=1),     # setelah T_obs
                              _watch(9, 2, F=0, U=60, window=2)]
        self.assertEqual(H.decide(late, self.big, self.n, 1, "F2")[0], base)

    def test_dto_identical_to_frozen_step3_detector(self):
        links = _scenario()
        rows = H.decide(links, self.big, self.n, 2, "F2")[0]
        ev = DD.evidence(links, self.n, {0}, None)
        ref = DD.detect(ev, self.n, "main", seed=2 * 7 + self.n * 101)[0]
        self.assertEqual([r["dto_decision"] for r in rows], [r["decision"] for r in ref])

    def test_k9_variant_is_opt_in(self):
        # observer 10 dgn b = 0.94 adalah satu-satunya pengamat node 5 (U = 0)
        links = _scenario() + [_watch(10, 0, F=50, heard_rxfail=47), _watch(10, 5, A=50)]
        pre = H.decide(links, self.big, self.n, 1, "F2")[0]
        k9 = H.decide(links, self.big, self.n, 1, "F2", b_max=0.8)[0]
        self.assertEqual(pre[5]["dto_decision"], "normal")
        self.assertEqual(k9[5]["dto_decision"], "insufficient_evidence")

    def test_deterministic(self):
        a = H.decide(_scenario(), self.big, self.n, 1, "F1")
        b = H.decide(_scenario(), self.big, self.n, 1, "F1")
        self.assertEqual(a, b)


class TestIsolationAttribution(unittest.TestCase):
    def test_counts_follow_selected_fusion_reason(self):
        rows = [
            {"isolate": "1", "reason": "bigan", "dto_decision": "malicious"},
            {"isolate": "1", "reason": "dto", "dto_decision": "malicious"},
            {"isolate": "1", "reason": "dto+bigan", "dto_decision": "malicious"},
            {"isolate": "0", "reason": "none", "dto_decision": "normal"},
        ]
        self.assertEqual(HE._isolation_counts(rows), (3, 2, 1))


class TestNoLabels(unittest.TestCase):
    def test_source_reads_no_labels(self):
        code = re.sub(r'"""(.|\n)*?"""', "", inspect.getsource(H))
        code = re.sub(r"#[^\n]*", "", code)
        for tok in ("actual_mal", "load_ground_truth", "watchdog_audit", "load_audit",
                    "self_", "labels(", "[\"node_malicious\"]"):
            self.assertNotIn(tok, code, tok)

    def test_bigan_loader_ignores_label_column(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "b.csv")
            with open(p, "w") as f:
                f.write("node_id,actual_mal,anomaly_score,threshold,pred_intrusion\n")
                f.write("0,GARBAGE,x,y,1\n1,GARBAGE,x,y,0\n")
            np.testing.assert_array_equal(H.load_bigan_pred(p, 2), [True, False])
            with self.assertRaises(ValueError):
                H.load_bigan_pred(p, 3)                # node 2 tidak ada
        finally:
            shutil.rmtree(d)

    def test_output_columns_have_no_label(self):
        self.assertEqual(S.check_no_leakage(H.DECISION_COLUMNS), [])
        self.assertEqual(S.BIGAN_INPUT_COLUMNS, ["node_id", "pred_intrusion"])

    def test_pilot_predictions_require_matching_label_free_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = {key: os.path.join(directory, key + ".csv") for key in ("node", "links")}
            for path in telemetry.values():
                with open(path, "w") as stream:
                    stream.write("recorded telemetry\n")
            path = os.path.join(directory, "predictions.csv")
            with open(path, "w") as stream:
                stream.write("node_id,score,threshold,pred_intrusion\n0,0.5,0.4,1\n1,0.1,0.4,0\n")
            meta = {"nodes": 2, "seed": 4, "window": 0, "contains_ground_truth": False,
                    "source_features_sha256": {key: H.sha256(value)
                                               for key, value in telemetry.items()}}
            with open(path + ".meta.json", "w") as stream:
                json.dump(meta, stream)
            np.testing.assert_array_equal(H.load_pilot_pred(path, 2, 4, telemetry), [True, False])
            with open(telemetry["links"], "a") as stream:
                stream.write("changed\n")
            with self.assertRaisesRegex(ValueError, "telemetry links"):
                H.load_pilot_pred(path, 2, 4, telemetry)


class TestCppContract(unittest.TestCase):
    def test_pilot_hybrid_bigan_uses_hybrid_decision_after_run(self):
        with open(CC) as stream:
            source = stream.read()
        start = source.index("static void EvaluateBiganAlarm()")
        end = source.index("template <typename EnergyContainer>", start)
        evaluation = source[start:end]
        self.assertIn("cfg::hybridPilotBigan ? g_hybrid.Get(i).biganPred", evaluation)
        self.assertGreater(source.index("EvaluateBiganAlarm();"), source.index("Simulator::Run();"))
        self.assertIn('cmd.AddValue("hybridPilotBigan"', source)
        self.assertIn('cfg::hybridPilotBigan && cfg::idsSource != "file"', source)
        self.assertIn('!cfg::hybridPilotBigan &&', source)

    def test_headers_match_cpp_loader(self):
        src = open(CC).read()
        self.assertIn('"' + ",".join(H.DECISION_COLUMNS) + '"', src)
        self.assertIn('"node_id,dest_sink,next_hop,next_hop_is_sink,slot"', src)
        self.assertEqual(H.ROUTE_COLUMNS[:5],
                         ["node_id", "dest_sink", "next_hop", "next_hop_is_sink", "slot"])
        for opt in ('"idsSource"', '"idsDir"', 'idsSource    = "cpp"'):
            self.assertIn(opt, src)

    def test_isolation_counters_follow_fusion_reason(self):
        src = open(CC).read()
        self.assertIn("d.reason = f[4];", src)
        self.assertIn('h.reason == "dto+bigan"', src)
        self.assertIn('h.reason == "bigan") ++g_isolatedBiganOnly', src)

    def test_written_files_are_lf_and_header_byte_exact(self):
        # loader C++ membandingkan header persis lewat std::getline: tanpa '\r'
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "h.csv")
            H.write_rows(p, [{"node_id": 0, "dto_decision": "normal", "bigan_pred": 0,
                              "isolate": 0, "reason": "none"}], H.DECISION_COLUMNS)
            raw = open(p, "rb").read()
            self.assertNotIn(b"\r", raw)
            first = raw.split(b"\n", 1)[0].decode()
            self.assertIn('if (line != "' + first + '")', open(CC).read())
            q = os.path.join(d, "r.csv")
            H.write_rows(q, [{c: 0 for c in H.ROUTE_COLUMNS} | {"q_value": 0.5}],
                         H.ROUTE_COLUMNS)
            self.assertNotIn(b"\r", open(q, "rb").read())
        finally:
            shutil.rmtree(d)

    def test_timing_constants(self):
        self.assertAlmostEqual(H.T_OBS + 1.0, H.T_IDS)   # wdLate = 1.0 s (K12)
        self.assertIn("Seconds(8.3),  &PhaseIds", open(CC).read())


@unittest.skipUnless(os.path.exists(MODEL) and os.path.isdir(os.path.join(RES, "routes_stage2")),
                     "model TLDQN / tabel rute tidak ada")
class TestReroute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore")
        import torch
        from honeycomb_topology import K_ACTIONS
        from routing_env import EnvConfig, STATE_DIM
        from tldqn_routing import DQNConfig, QNet
        d = DQNConfig()
        cls.q = QNet(STATE_DIM, K_ACTIONS, d.hidden, d.n_hidden)
        cls.q.load_state_dict(torch.load(MODEL, map_location="cpu"))
        cls.q.eval()
        cls.cfg = EnvConfig()

    def _load(self, n, s, rd="routes_stage2", td="step2/trust_stage1"):
        env, _, _ = H.load_route_env(os.path.join(RES, rd), n, s,
                                     os.path.join(RES, td) if td else None, self.cfg)
        return env, H.load_table(os.path.join(RES, rd, f"tldqn_nexthop_{n}_s{s}.csv"))

    @staticmethod
    def _strip(rows):
        return [{k: v for k, v in r.items() if k != "q_value"}
                for r in sorted(rows, key=lambda r: (r["node_id"], r["dest_sink"]))]

    def test_no_isolation_reproduces_tables(self):
        for rd, td in (("routes_stage2", "step2/trust_stage1"), ("routes_stage1", None)):
            for n in (20, 60, 100):
                env, rows = self._load(n, 1, rd, td)
                new, rep = H.reroute(rows, env, self.q, [])
                self.assertEqual(self._strip(new), self._strip(rows), (rd, n))
                self.assertEqual((rep["changed_entries"], rep["failed_entries"]), ([], []))

    def test_pilot_cli_reuses_label_free_predictions_and_refuses_overwrite(self):
        source = os.path.join(RES, "bigan_test_4_6_20261107_214507")
        routes = os.path.join(RES, "bigan_pilot_test_4_6", "routes")
        predictions = os.path.join(ML, "reports", "bigan_ns3_pilot", "pilot_20261107_211217",
                                   "predictions_test_4_6", "bigan_pilot_predictions_100_s4.csv")
        if not (os.path.isfile(predictions) and os.path.isdir(source) and os.path.isdir(routes)):
            self.skipTest("fixture telemetry pilot tidak tersedia")
        with tempfile.TemporaryDirectory() as directory:
            telem_dir = os.path.join(directory, "telemetry")
            pred_dir = os.path.join(directory, "predictions")
            output = os.path.join(directory, "output")
            os.makedirs(telem_dir)
            os.makedirs(pred_dir)
            for name in ("telemetry_100_s4.csv", "telemetry_links_100_s4.csv"):
                shutil.copyfile(os.path.join(source, name), os.path.join(telem_dir, name))
            telemetry = S.paths(telem_dir, 100, 4)
            with open(telemetry["meta"], "w") as stream:
                json.dump({"num_nodes": 100, "seed": 4, "sim_time_s": 10.0, "window_s": 7.3,
                           "wd_late_s": 1.0}, stream)
            pred_path = os.path.join(pred_dir, os.path.basename(predictions))
            shutil.copyfile(predictions, pred_path)
            with open(pred_path + ".meta.json", "w") as stream:
                json.dump({"nodes": 100, "seed": 4, "window": 0,
                           "contains_ground_truth": False,
                           "source_features_sha256": {key: H.sha256(telemetry[key])
                                                      for key in ("node", "links")}}, stream)
            args = ["--telem-dir", telem_dir, "--scenario-dir", os.path.join(directory, "unused"),
                    "--route-dir", routes, "--bigan-pred-dir", pred_dir,
                    "--out-dir", output, "--nodes", "100", "--seeds", "4", "--fusion", "F2"]
            with open(telemetry["meta"], "w") as stream:
                json.dump({"num_nodes": 100, "seed": 4, "sim_time_s": 8.0, "window_s": 7.3,
                           "wd_late_s": 1.0}, stream)
            with self.assertRaisesRegex(ValueError, "sebelum T_ids"):
                H.main(args)
            self.assertFalse(os.path.exists(output))
            with open(telemetry["meta"], "w") as stream:
                json.dump({"num_nodes": 100, "seed": 4, "sim_time_s": 10.0, "window_s": 7.3,
                           "wd_late_s": 1.0}, stream)
            self.assertEqual(H.main(args), 0)
            with open(os.path.join(output, "hybrid_decisions_100_s4.csv"), newline="") as stream:
                decisions = list(csv.DictReader(stream))
            self.assertEqual(len(decisions), 100)
            self.assertEqual(sum(int(row["bigan_pred"]) for row in decisions), 11)
            self.assertTrue(all(int(row["isolate"]) == (row["dto_decision"] == "malicious")
                                for row in decisions))
            with open(os.path.join(output, "hybrid_meta.json")) as stream:
                meta = json.load(stream)
            self.assertEqual(meta["scenarios"]["100_s4"]["bigan_sha256"], H.sha256(pred_path))
            self.assertEqual(meta["scenarios"]["100_s4"]["telemetry_node_sha256"],
                             H.sha256(telemetry["node"]))
            with self.assertRaises(FileExistsError):
                H.main(args)

    def test_isolated_relay_is_avoided_without_fabricated_paths(self):
        n = 100
        env, rows = self._load(n, 1)
        topo = env.topo
        # relay yang paling sering dipakai sebagai next-hop sensor
        use = {}
        for r in rows:
            if not r["next_hop_is_sink"]:
                use[r["next_hop"]] = use.get(r["next_hop"], 0) + 1
        relay = max(use, key=lambda k: (use[k], -k))
        new, rep = H.reroute(rows, env, self.q, [relay])
        self.assertGreater(len(rep["changed_entries"]), 0)
        for r in new:
            c, t = r["node_id"], r["dest_sink"] + n
            j = n + r["next_hop"] if r["next_hop_is_sink"] else r["next_hop"]
            self.assertIn(j, topo.candidates(c, t))          # hanya kandidat TLDQN
            if c != relay and j == relay:
                self.assertIn({"node_id": c, "dest_sink": r["dest_sink"],
                               "next_hop_kept": relay, "next_hop_is_sink": 0},
                              rep["failed_entries"])
        changed = {(x["node_id"], x["dest_sink"]) for x in rep["changed_entries"]}
        for o, r in zip(self._strip(rows), self._strip(new)):
            if (o["node_id"], o["dest_sink"]) not in changed:
                self.assertEqual(o, r)                        # minimal: sisanya tetap
        for p in rep["paths"]:                                # bebas loop, status eksplisit
            self.assertIn(p["status"], ("ok", "failed"))

    def test_no_alternative_is_reported_as_failure(self):
        n = 20
        env, rows = self._load(n, 1)
        topo = env.topo
        # cari pasangan dgn kandidat sensor saja, lalu isolasi SEMUA kandidatnya
        for c, t in topo.reachable_pairs():
            cand = topo.candidates(c, t)
            if all(not topo.is_sink(j) for j in cand) and c not in cand:
                break
        new, rep = H.reroute(rows, env, self.q, cand)
        self.assertIn((c, t - n), {(x["node_id"], x["dest_sink"]) for x in rep["failed_entries"]})
        kept = next(r for r in new if (r["node_id"], r["dest_sink"]) == (c, t - n))
        orig = next(r for r in rows if (r["node_id"], r["dest_sink"]) == (c, t - n))
        self.assertEqual(self._strip([kept]), self._strip([orig]))   # entri dibiarkan
        if c not in cand:
            st = [p for p in rep["paths"] if p["source"] == c]
            if st and topo.dest[c] == t:
                self.assertEqual(st[0]["status"], "failed")


_CXX = shutil.which("clang++") or shutil.which("g++")


class TestBenignPdr(unittest.TestCase):
    """PDR khusus sumber jujur: definisi C++ (BenignDelivery) + pemeriksa Python."""

    SRC = open(CC).read()

    def test_python_definition(self):
        self.assertEqual(HE.benign_pdr(200, 150), 75.0)
        self.assertTrue(np.isnan(HE.benign_pdr(0, 0)))        # tidak terdefinisi, bukan 100
        for bad in ((10, 11), (-1, 0)):
            with self.assertRaises(ValueError):
                HE.benign_pdr(*bad)

    @unittest.skipUnless(_CXX, "kompiler C++ tidak ada")
    def test_cpp_struct_classification_aggregation_and_pdr(self):
        import subprocess
        body = re.search(r"struct BenignDelivery\n\{.*?\n\};\n", self.SRC, re.S)
        self.assertIsNotNone(body)
        prog = ("#include <cstdint>\n#include <cstdio>\n#include <cmath>\n#include <limits>\n"
                + body.group(0) + r'''
int main() {
  BenignDelivery e;                                    // tanpa aliran
  std::printf("empty %d %d\n", (int)e.Defined(), (int)std::isnan(e.Pdr()));
  BenignDelivery b;
  b.Add(true, true, 50, 48);                           // sensor jujur
  b.Add(true, true, 50, 50);                           // sensor jujur
  b.Add(true, false, 120, 10);                         // sensor malicious: dibuang
  b.Add(false, true, 30, 0);                           // bukan sensor: dibuang
  b.Add(true, true, 0, 0);                             // aliran jujur tanpa paket
  std::printf("agg %llu %llu %llu %d %.6f\n", (unsigned long long)b.tx,
              (unsigned long long)b.rx, (unsigned long long)b.flows, (int)b.Defined(), b.Pdr());
  BenignDelivery z; z.Add(true, true, 0, 0);           // aliran ada, tx = 0
  std::printf("zero %d %d\n", (int)z.Defined(), (int)std::isnan(z.Pdr()));
  return 0;
}
''')
        d = tempfile.mkdtemp()
        try:
            src, exe = os.path.join(d, "b.cc"), os.path.join(d, "b")
            open(src, "w").write(prog)
            subprocess.run([_CXX, "-std=c++17", "-o", exe, src], check=True,
                           capture_output=True)
            out = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
        finally:
            shutil.rmtree(d)
        self.assertEqual(out.splitlines(),
                         ["empty 0 1", "agg 100 98 3 1 98.000000", "zero 0 1"])

    def test_rows_written_only_in_file_none_modes_and_after_run(self):
        src = self.SRC
        block = src[src.index('csv << "ids_mode,"'):src.index('NS_LOG_UNCOND("\\nMetrik ditulis')]
        self.assertIn('if (cfg::idsSource != "cpp")',
                      src[src.index('csv << "ids_mode,"') - 200:src.index('csv << "ids_mode,"')])
        for row in ("benign_tx_packets,", "benign_rx_packets,", "benign_pdr_percent,",
                    "benign_pdr_defined,", "benign_pdr_percent,nan"):
            self.assertIn(row, block)
            # semua kemunculan berada di blok non-cpp (tidak ditulis di tempat lain)
            self.assertEqual(src.count('"' + row), block.count('"' + row), row)
        # label dipakai pasca-simulasi saja: pengisian setelah Simulator::Run()
        self.assertGreater(src.index("benign.Add("), src.index("Simulator::Run();"))

    def test_evaluate_checks_consistency(self):
        d = tempfile.mkdtemp()
        try:
            dec = os.path.join(d, "dec")
            os.makedirs(dec)
            H.write_rows(os.path.join(dec, "hybrid_decisions_20_s1.csv"),
                         [{"node_id": i, "dto_decision": "normal", "bigan_pred": 0,
                           "isolate": 0, "reason": "none"} for i in range(20)],
                         H.DECISION_COLUMNS)
            json.dump({"fusion": "F2", "dto": {}, "scenarios": {"20_s1": {"reroute": {
                "paths": [], "changed_entries": [], "failed_entries": []}}}},
                open(os.path.join(dec, "hybrid_meta.json"), "w"))

            def met(name, tx, rx, pdr):
                p = os.path.join(d, name)
                with open(p, "w") as f:
                    f.write("metric,value\npdr_percent,90\n"
                            f"benign_tx_packets,{tx}\nbenign_rx_packets,{rx}\n"
                            f"benign_pdr_percent,{pdr}\n")
                return p

            met("A_20_s1.csv", 100, 90, 90)
            met("B_20_s1.csv", 0, 0, "nan")                  # tidak terdefinisi: dilewati
            r = HE.evaluate(dec, RES, os.path.join(d, "A_{tag}.csv"),
                            os.path.join(d, "B_{tag}.csv"), [20], [1])
            self.assertNotIn("benign_pdr_percent", r["network_paired"])
            met("B_20_s1.csv", 100, 95, 99.0)                # tidak konsisten dgn rx/tx
            with self.assertRaises(ValueError):
                HE.evaluate(dec, RES, os.path.join(d, "A_{tag}.csv"),
                            os.path.join(d, "B_{tag}.csv"), [20], [1])
            met("B_20_s1.csv", 100, 95, 95.0)
            r = HE.evaluate(dec, RES, os.path.join(d, "A_{tag}.csv"),
                            os.path.join(d, "B_{tag}.csv"), [20], [1])
            self.assertAlmostEqual(r["network_paired"]["benign_pdr_percent"]["mean_B_minus_A"], 5.0)
        finally:
            shutil.rmtree(d)


S4 = os.path.join(RES, "step4")


@unittest.skipUnless(os.path.isdir(os.path.join(S4, "telemetry_s4B_F2")), "data pilot tidak ada")
class TestPilotGatesOnStoredData(unittest.TestCase):
    """Gerbang pilot percobaan 2 (11.7) dapat direproduksi dari data tersimpan."""

    def test_decisions_applied_and_inputs_match(self):
        for V in ("F2", "F1", "K9_F2"):
            dec = os.path.join(S4, f"dec_{V}")
            self.assertTrue(HE.applied(dec, os.path.join(S4, "metrics_{tag}_s4B_" + V + ".csv"),
                                       os.path.join(S4, "log_{tag}_s4B_" + V + ".txt"),
                                       [20, 60, 100], [1])["pass"], V)
            self.assertTrue(HE.same_inputs(dec, os.path.join(S4, "telemetry_s4A"),
                                           [20, 60, 100], [1])["pass"], V)
            self.assertTrue(HE.determinism(os.path.join(S4, "telemetry_s4A"),
                                           os.path.join(S4, f"telemetry_s4B_{V}"),
                                           [20, 60, 100], [1])["pass"], V)

    def test_same_inputs_rejects_other_telemetry(self):
        self.assertFalse(HE.same_inputs(os.path.join(S4, "dec_F2"),
                                        os.path.join(S4, "telemetry_s4tw"), [20], [1])["pass"])


class TestMetricsIdentical(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def _w(self, name, rows):
        p = os.path.join(self.d, name)
        with open(p, "w") as f:
            f.write("metric,value\n" + "".join(f"{k},{v}\n" for k, v in rows))
        return p

    def test_wallclock_rows_ignored_but_reported(self):
        a = self._w("a.csv", [("pdr_percent", "97.1"), ("rt_compute_ms", "0.0966"),
                              ("computation_overhead_percent", "23.23")])
        b = self._w("b.csv", [("pdr_percent", "97.1"), ("rt_compute_ms", "0.0967"),
                              ("computation_overhead_percent", "23.22")])
        r = HE.identical(a, b, metrics=True)
        self.assertTrue(r["identical"])
        self.assertEqual(r["wallclock_ignored"]["rt_compute_ms"], {"a": "0.0966", "b": "0.0967"})
        self.assertFalse(HE.identical(a, b)["identical"])          # mode byte tetap ketat

    def test_any_other_metric_difference_fails(self):
        a = self._w("a.csv", [("pdr_percent", "97.1"), ("rt_compute_ms", "1")])
        b = self._w("b.csv", [("pdr_percent", "97.2"), ("rt_compute_ms", "1")])
        r = HE.identical(a, b, metrics=True)
        self.assertFalse(r["identical"])
        self.assertEqual(r["differing_metrics"], ["pdr_percent"])

    def test_row_set_or_order_change_fails(self):
        a = self._w("a.csv", [("pdr_percent", "1"), ("latency_ms", "2")])
        b = self._w("b.csv", [("latency_ms", "2"), ("pdr_percent", "1")])
        c = self._w("c.csv", [("pdr_percent", "1"), ("latency_ms", "2"), ("ids_mode", "2")])
        self.assertFalse(HE.identical(a, b, metrics=True)["identical"])
        self.assertFalse(HE.identical(a, c, metrics=True)["identical"])   # baris baru = beda


class TestDeterminismGate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a, self.b = os.path.join(self.d, "A"), os.path.join(self.d, "B")
        for x in (self.a, self.b):
            os.makedirs(x)
            with open(os.path.join(x, "ids_snapshot_20_s1.csv"), "w") as f:
                f.write("key,value\nt_s,8.3000000000000007\nevent_count,123\n")
            for name, cols in (("telemetry_20_s1.csv", S.NODE_COLUMNS),
                               ("telemetry_links_20_s1.csv", S.LINK_COLUMNS)):
                with open(os.path.join(x, name), "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(cols)
                    for win in (0, 1):
                        w.writerow([win if c == "window" else 1 for c in cols])

    def tearDown(self):
        shutil.rmtree(self.d)

    def _edit(self, name, col, window, value):
        p = os.path.join(self.b, name)
        rows = list(csv.reader(open(p)))
        h = rows[0]
        for r in rows[1:]:
            if r[h.index("window")] == str(window):
                r[h.index(col)] = value
        with open(p, "w", newline="") as f:
            csv.writer(f).writerows(rows)

    def test_identical_runs_pass(self):
        self.assertTrue(HE.determinism(self.a, self.b, [20], [1])["pass"])

    def test_snapshot_difference_fails(self):
        with open(os.path.join(self.b, "ids_snapshot_20_s1.csv"), "a") as f:
            f.write("x,1\n")
        self.assertFalse(HE.determinism(self.a, self.b, [20], [1])["pass"])

    def test_dto_input_difference_in_window0_fails(self):
        self._edit("telemetry_links_20_s1.csv", "wd_unobserved_clean", 0, "9")
        self.assertFalse(HE.determinism(self.a, self.b, [20], [1])["pass"])

    def test_later_window_and_lookahead_column_reported_not_failed(self):
        self._edit("telemetry_links_20_s1.csv", "wd_unobserved_clean", 1, "9")
        self._edit("telemetry_links_20_s1.csv", "wd_heard_after_timeout", 0, "9")
        r = HE.determinism(self.a, self.b, [20], [1])
        self.assertTrue(r["pass"])
        self.assertEqual(r["scenarios"][0]["full_links_window0_differing_columns"],
                         ["wd_heard_after_timeout"])


if __name__ == "__main__":
    unittest.main()
