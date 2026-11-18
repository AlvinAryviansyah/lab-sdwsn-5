#!/usr/bin/env python3
"""
step4_full.py  --  sweep penuh langkah 4: keputusan + daftar run B, lalu laporan gabungan
--------------------------------------------------------------------------------------
  decide  dari run A (results/step4/full/telemetry_s4{f,c}A): keputusan F2, F1, K9_F2
          (hybrid_ids, definisi tidak berubah) untuk stage2 + ctrl0, dedup K9_F2
          (dilewati bila isolate DAN reroute identik dengan F2), tulis daftar run B
  report  gerbang per skenario (status run, determinisme A vs B, applied) + evaluasi
          (label hanya di hybrid_eval) -> ml/reports/step4_full_report.json + markdown
Kegagalan tidak dilewati diam-diam: skenario dengan run gagal / berkas hilang dicatat
eksplisit dan dikeluarkan dari agregat (dilaporkan).
"""

import argparse
import csv
import filecmp
import json
import os
import sys

import numpy as np

import hybrid_eval as HE
import hybrid_ids as H

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "ns3-sim", "results")
FULL = os.path.join(RES, "step4", "full")
LISTS = os.path.join(HERE, "..", "ns3-sim", "step4_lists")
ALL = [20, 30, 40, 50, 60, 70, 80, 90, 100]
GROUPS = {
    "stage2": {"nodes": ALL, "a_tag": "_s4fA", "b_tag": "_s4fB", "route": "routes_stage2",
               "trust": os.path.join(RES, "step2", "trust_stage1"), "extra": ""},
    "ctrl0": {"nodes": [20, 60, 100], "a_tag": "_s4cA", "b_tag": "_s4cB",
              "route": "routes_stage1", "trust": None, "extra": " --grayholeDrop=0"},
}
SEEDS = [1, 2, 3]
VARIANTS = {"F2": ("F2", 0.0), "F1": ("F1", 0.0), "K9_F2": ("F2", 0.8)}


def scen(g):
    return [(n, s) for s in SEEDS for n in GROUPS[g]["nodes"]]


def dec_dir(g, v):
    return os.path.join(FULL, f"dec_{g}_{v}")


def decide():
    lines, dedup = [], {}
    for g, cfg in GROUPS.items():
        telem = os.path.join(FULL, f"telemetry{cfg['a_tag']}")
        for v, (fusion, bmax) in VARIANTS.items():
            args = ["--telem-dir", telem, "--scenario-dir", RES,
                    "--route-dir", os.path.join(RES, cfg["route"]), "--out-dir", dec_dir(g, v),
                    "--nodes", *map(str, cfg["nodes"]), "--seeds", *map(str, SEEDS),
                    "--fusion", fusion, "--b-max", str(bmax)]
            if cfg["trust"]:
                args += ["--trust-dir", cfg["trust"]]
            H.main(args)
        dedup[g] = {}
        for n, s in scen(g):
            tag = f"{n}_s{s}"
            f2 = [r["isolate"] for r in HE._hybrid(os.path.join(dec_dir(g, "F2"), f"hybrid_decisions_{tag}.csv"))]
            k9 = [r["isolate"] for r in HE._hybrid(os.path.join(dec_dir(g, "K9_F2"), f"hybrid_decisions_{tag}.csv"))]
            same_rr = filecmp.cmp(os.path.join(dec_dir(g, "F2"), f"reroute_nexthop_{tag}.csv"),
                                  os.path.join(dec_dir(g, "K9_F2"), f"reroute_nexthop_{tag}.csv"),
                                  shallow=False)
            same_dec = filecmp.cmp(os.path.join(dec_dir(g, "F2"), f"hybrid_decisions_{tag}.csv"),
                                   os.path.join(dec_dir(g, "K9_F2"), f"hybrid_decisions_{tag}.csv"),
                                   shallow=False)
            run_k9 = not (f2 == k9 and same_rr)
            dedup[g][tag] = {"decisions_identical": same_dec, "isolate_identical": f2 == k9,
                             "reroute_identical": same_rr, "simulate": run_k9}
        for v in VARIANTS:
            for n, s in scen(g):
                tag = f"{n}_s{s}"
                if v == "K9_F2" and not dedup[g][tag]["simulate"]:
                    continue
                lines.append(f"{n} {s} {cfg['b_tag']}_{v} results/{cfg['route']} "
                             f"results/step4f/telemetry{cfg['b_tag']}_{v} --idsSource=file "
                             f"--idsDir=results/step4f/dec_{g}_{v} --telemWindow=7.3{cfg['extra']}")
    os.makedirs(LISTS, exist_ok=True)
    with open(os.path.join(LISTS, "runB.txt"), "w") as f:
        f.write("# Run B langkah 4 (idsSource=file): F2 + F1 semua skenario; K9_F2 hanya bila "
                "isolate/reroute berbeda dari F2\n" + "\n".join(lines) + "\n")
    with open(os.path.join(FULL, "k9_dedup.json"), "w") as f:
        json.dump(dedup, f, indent=1)
    for g in GROUPS:
        k = sum(x["simulate"] for x in dedup[g].values())
        d = sum(not x["decisions_identical"] for x in dedup[g].values())
        print(f"{g}: K9_F2 keputusan berbeda dari F2 di {d}/{len(dedup[g])} skenario; "
              f"perlu simulasi {k} (isolasi/reroute berbeda)")
    print(f"run B: {len(lines)} baris -> ns3-sim/step4_lists/runB.txt")
    return 0


def _status(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {(int(r["n"]), int(r["seed"]), r["out_tag"]): int(r["rc"]) for r in csv.DictReader(f)}


def _agg(vals):
    v = np.array([x for x in vals if x is not None and not np.isnan(x)], float)
    return None if v.size == 0 else {"n": int(v.size), "mean": float(v.mean()),
                                     "median": float(np.median(v)), "min": float(v.min()),
                                     "max": float(v.max())}


def report(out_json, out_md):
    st = {**_status(os.path.join(FULL, "status_runA.csv")),
          **_status(os.path.join(FULL, "status_runB.csv"))}
    dedup = json.load(open(os.path.join(FULL, "k9_dedup.json")))
    rep = {"coverage": {}, "failures": [], "gates": {}, "variants": {}}
    for g, cfg in GROUPS.items():
        a_dir = os.path.join(FULL, f"telemetry{cfg['a_tag']}")
        for v in VARIANTS:
            key = f"{g}/{v}"
            b_tag = f"{cfg['b_tag']}_{v}"
            sim_v = {}                       # skenario -> sumber metrik B (varian sendiri / F2)
            for n, s in scen(g):
                tag = f"{n}_s{s}"
                src = v
                if v == "K9_F2" and not dedup[g][tag]["simulate"]:
                    src = "F2"
                bt = f"{cfg['b_tag']}_{src}"
                ok = True
                for t in (cfg["a_tag"], bt):
                    rc = st.get((n, s, t))
                    mpath = os.path.join(FULL, f"metrics_{tag}{t}.csv")
                    if rc is None or rc != 0 or not os.path.exists(mpath):
                        ok = False
                        rep["failures"].append({"group": g, "variant": v, "n": n, "seed": s,
                                                "run": t, "rc": rc,
                                                "metrics_exists": os.path.exists(mpath)})
                if ok:
                    sim_v[(n, s)] = src
            good = sorted(sim_v)
            rep["coverage"][key] = {"scenarios": len(scen(g)), "evaluated": len(good),
                                    "k9_reused_f2_simulation": sum(1 for x in sim_v.values()
                                                                   if v == "K9_F2" and x == "F2")}
            gates = {"determinism": [], "applied": []}
            per = []
            for n, s in good:
                src = sim_v[(n, s)]
                bt = f"{cfg['b_tag']}_{src}"
                b_dir = os.path.join(FULL, f"telemetry{bt}")
                det = HE.determinism(a_dir, b_dir, [n], [s])
                app = HE.applied(dec_dir(g, src), os.path.join(FULL, "metrics_{tag}" + bt + ".csv"),
                                 os.path.join(FULL, "log_{tag}" + bt + ".txt"), [n], [s])
                gates["determinism"].append(det["pass"])
                gates["applied"].append(app["pass"])
                ev = HE.evaluate(dec_dir(g, v), RES, os.path.join(FULL, "metrics_{tag}" + cfg["a_tag"] + ".csv"),
                                 os.path.join(FULL, "metrics_{tag}" + bt + ".csv"), [n], [s])
                sc = ev["scenarios"][0]
                sc["metrics_from"] = src
                per.append(sc)
            rep["gates"][key] = {k: [int(sum(x)), len(x)] for k, x in gates.items()}
            # agregat
            pooled = {k: {"TP": 0, "FP": 0, "FN": 0, "TN": 0} for k in ("dto", "bigan", "isolate")}
            for sc in per:
                for k in pooled:
                    for kk in pooled[k]:
                        pooled[k][kk] += sc[k][kk]
            net = {}
            for m in HE.NET_METRICS:
                A = [sc["network"][m]["A"] for sc in per]
                B = [sc["network"][m]["B"] for sc in per]
                D = [b - a for a, b in zip(A, B) if a is not None and b is not None
                     and not (np.isnan(a) or np.isnan(b))]
                e = {"A": _agg(A), "B": _agg(B), "B_minus_A": _agg(D),
                     "B_gt_A": int(sum(d > 0 for d in D)), "B_lt_A": int(sum(d < 0 for d in D)),
                     "equal": int(sum(d == 0 for d in D))}
                if len(D) >= 6 and any(d != 0 for d in D):
                    from scipy.stats import wilcoxon
                    e["wilcoxon_p"] = float(wilcoxon(D).pvalue)
                net[m] = e
            sums = {k: [int(sum(sc["network"][k][x] for sc in per)) for x in ("A", "B")]
                    for k in ("benign_tx_packets", "benign_rx_packets", "grayhole_drops")}
            ids = {k: int(sum(sc["ids_counters_B"][k] for sc in per)) for k in HE.IDS_METRICS}
            honest = int(sum(sc["isolate"]["FP"] for sc in per))
            rep["variants"][key] = {"detection_pooled": {k: HE.scores(c) for k, c in pooled.items()},
                                    "honest_isolated": honest, "network": net, "sums_A_B": sums,
                                    "ids_counters_B": ids,
                                    "failed_paths": int(sum(sc["reroute"]["failed_paths"] for sc in per)),
                                    "scenarios": per}
    with open(out_json, "w") as f:
        json.dump(rep, f, indent=1)
    write_md(rep, out_md)
    print(json.dumps({"coverage": rep["coverage"], "failures": len(rep["failures"]),
                      "gates": rep["gates"]}, indent=1))
    return 0


def _f(x, d=3):
    return "–" if x is None else f"{x:.{d}f}"


def write_md(rep, path):
    L = ["# Langkah 4: hasil sweep penuh (dihasilkan `ml/step4_full.py report`)", "",
         "Data: `ns3-sim/results/step4/full/`. JSON lengkap: `ml/reports/step4_full_report.json`.",
         "Desain dan keputusan: `docs/STEP4_HYBRID_IDS_DESIGN.md` (bagian 11).", "",
         "## Cakupan dan kegagalan", "",
         "| Grup / varian | Skenario | Dievaluasi | K9_F2 memakai simulasi F2 (identik) |", "|---|---|---|---|"]
    for k, c in rep["coverage"].items():
        L.append(f"| {k} | {c['scenarios']} | {c['evaluated']} | {c['k9_reused_f2_simulation']} |")
    L += ["", f"Run gagal / berkas hilang: **{len(rep['failures'])}**."]
    for x in rep["failures"]:
        L.append(f"- {x['group']}/{x['variant']} n={x['n']} s={x['seed']} run `{x['run']}`: "
                 f"rc={x['rc']}, metrik ada={x['metrics_exists']}")
    L += ["", "## Gerbang per skenario", "", "| Grup / varian | Determinisme A vs B | applied |",
          "|---|---|---|"]
    for k, gt in rep["gates"].items():
        L.append(f"| {k} | {gt['determinism'][0]}/{gt['determinism'][1]} | "
                 f"{gt['applied'][0]}/{gt['applied'][1]} |")
    L += ["", "## Deteksi pada T_ids (pool skenario; label hanya evaluasi)", "",
          "| Grup / varian | Sumber | TP | FP | FN | Precision | Recall | FPR |",
          "|---|---|---|---|---|---|---|---|"]
    for k, v in rep["variants"].items():
        for src, sc in v["detection_pooled"].items():
            L.append(f"| {k} | {src} | {sc['TP']} | {sc['FP']} | {sc['FN']} | {_f(sc['precision'])} | "
                     f"{_f(sc['recall'])} | {_f(sc['fpr'])} |")
    L += ["", "## Jaringan, B vs A (berpasangan per skenario)", "",
          "| Grup / varian | Metrik | A rata-rata | B rata-rata | B−A rata-rata | B>A / B<A / = | Wilcoxon p |",
          "|---|---|---|---|---|---|---|"]
    for k, v in rep["variants"].items():
        for m in ("pdr_percent", "benign_pdr_percent", "packet_drop_ratio_percent", "grayhole_drops",
                  "throughput_kbps", "latency_ms", "energy_consumption_J"):
            e = v["network"][m]
            if e["B_minus_A"] is None:
                continue
            L.append(f"| {k} | {m} | {_f(e['A']['mean'])} | {_f(e['B']['mean'])} | "
                     f"{_f(e['B_minus_A']['mean'], 4)} | {e['B_gt_A']}/{e['B_lt_A']}/{e['equal']} | "
                     f"{_f(e.get('wilcoxon_p'), 4)} |")
    L += ["", "## Paket sumber jujur dan isolasi (jumlah atas skenario)", "",
          "| Grup / varian | paket jujur tx A → B | paket jujur rx A → B | drop grayhole A → B | "
          "node jujur diisolasi | isolasi DTO | isolasi Bi-GAN saja | drop transit isolasi | jalur gagal |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, v in rep["variants"].items():
        s, i = v["sums_A_B"], v["ids_counters_B"]
        L.append(f"| {k} | {s['benign_tx_packets'][0]} → {s['benign_tx_packets'][1]} | "
                 f"{s['benign_rx_packets'][0]} → {s['benign_rx_packets'][1]} | "
                 f"{s['grayhole_drops'][0]} → {s['grayhole_drops'][1]} | {v['honest_isolated']} | "
                 f"{i['isolated_by_dto']} | {i['isolated_by_bigan_only']} | "
                 f"{i['isolation_transit_drops']} | {v['failed_paths']} |")
    L += ["", "## Keterbatasan", "",
          "- DTO memutuskan pada T_ids = 8.3 s dari observasi [0, 7.3 s). Cakupannya lebih kecil "
          "daripada DTO langkah 3 (akhir run).",
          "- Bi-GAN memakai sampel NSL-KDD yang ditugaskan berdasarkan label skenario: bukan deteksi "
          "independen dari trafik NS-3 (K14). F1 adalah aturan fusi eksperimental yang tidak disebut paper.",
          "- PDR gabungan mencampur efek berhentinya trafik penyerang. Untuk perlindungan trafik jujur, "
          "pakai `benign_*` (tx dan rx, bukan rasio saja).",
          "- Energi tetap Not Available untuk DTO (K10). Flooding hanya bisa ditangkap Bi-GAN.",
          "- Metrik waktu-dinding (`rt_compute_ms`, `computation_overhead_percent`) tidak deterministik.",
          "- K9_F2 yang isolasi dan reroute-nya identik dengan F2 tidak disimulasikan ulang; metrik jaringannya "
          "diambil dari run F2 (identik terbukti pada pilot).",
          "- Delegator lanjutan, alarm terdistribusi, dan reroute lanjutan belum ada (langkah 5)."]
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("decide")
    r = sub.add_parser("report")
    r.add_argument("--out-json", default=os.path.join(HERE, "reports", "step4_full_report.json"))
    r.add_argument("--out-md", default=os.path.join(HERE, "..", "docs", "STEP4_RESULTS.md"))
    a = ap.parse_args(argv)
    return decide() if a.cmd == "decide" else report(a.out_json, a.out_md)


if __name__ == "__main__":
    sys.exit(main())
