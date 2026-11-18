#!/usr/bin/env python3
"""
hybrid_eval.py  --  validasi & evaluasi langkah 4 (Hybrid IDS + IPS). Label HANYA di sini.
--------------------------------------------------------------------------------------
Subperintah:
  determinism  gerbang K12: snapshot pra-tindakan (ids_snapshot_*) dan baris telemetry
               window 0 run A (none) vs run B (file) harus byte-identik
  identical    dua berkas metrik identik (regresi default --idsSource=cpp vs hasil langkah 2,
               dan passivity --telemWindow)
  evaluate     deteksi pada T_ids (DTO / Bi-GAN / isolasi hybrid) + prevensi + jaringan
               berpasangan (run B vs run A) + laporan reroute
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

from dto_eval import conf, labels, scores
from telemetry_schema import load_metrics, paths

NET_METRICS = ["pdr_percent", "benign_pdr_percent", "benign_tx_packets", "benign_rx_packets",
               "packet_drop_ratio_percent", "throughput_kbps", "latency_ms",
               "energy_consumption_J", "grayhole_drops", "control_overhead_mps"]


def benign_pdr(tx, rx):
    """Definisi yang sama dengan C++ BenignDelivery: tx = 0 -> NaN (bukan 100%)."""
    if tx < 0 or rx < 0 or rx > tx:
        raise ValueError(f"paket tidak valid: tx={tx}, rx={rx}")
    return float("nan") if tx == 0 else 100.0 * rx / tx
IDS_METRICS = ["isolation_transit_drops", "isolated_by_dto", "isolated_by_bigan_only",
               "bigan_alarms", "reroute_changed", "reroute_unresolved", "nodes_blocked",
               "attackers_blocked"]


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def window_rows(path, window=0, columns=None):
    """Baris telemetry window == `window` sebagai daftar tuple teks (kolom terpilih)."""
    with open(path) as f:
        rd = csv.reader(f)
        header = next(rd)
        idx = [header.index(c) for c in (columns or header)]
        w = header.index("window")
        return [tuple(r[i] for i in idx) for r in rd if r[w] == str(window)]


def differing_columns(path_a, path_b, window=0):
    with open(path_a) as f:
        header = next(csv.reader(f))
    return [c for c in header
            if window_rows(path_a, window, [c]) != window_rows(path_b, window, [c])]


def determinism(dir_a, dir_b, nodes, seeds):
    """Gerbang K12. LULUS bila (1) snapshot pra-tindakan pada T_ids byte-identik dan
    (2) kolom masukan DTO pada window 0 identik. Baris window 0 penuh dilaporkan
    terpisah: kolom yang melihat ke depan (mis. wd_heard_after_timeout, terdengar setelah
    wdLate dan bisa setelah T_ids) boleh berbeda tanpa melanggar kausalitas."""
    from telemetry_schema import DTO_INPUT_LINK_COLUMNS
    out = []
    for n in nodes:
        for s in seeds:
            tag = f"{n}_s{s}"
            snap = f"ids_snapshot_{tag}.csv"
            pa, pb = paths(dir_a, n, s), paths(dir_b, n, s)
            r = {"n": n, "seed": s,
                 "snapshot_identical": _read(os.path.join(dir_a, snap))
                 == _read(os.path.join(dir_b, snap)),
                 "dto_input_window0_identical":
                     window_rows(pa["links"], 0, DTO_INPUT_LINK_COLUMNS)
                     == window_rows(pb["links"], 0, DTO_INPUT_LINK_COLUMNS)}
            for k in ("node", "links"):
                r[f"full_{k}_window0_differing_columns"] = differing_columns(pa[k], pb[k])
            with open(os.path.join(dir_a, snap)) as f:
                kv = dict(ln.strip().split(",", 1) for ln in f if "," in ln)
            r["snapshot_t_s"] = float(kv["t_s"])
            r["pass"] = r["snapshot_identical"] and r["dto_input_window0_identical"]
            out.append(r)
    return {"pass": all(r["pass"] for r in out), "scenarios": out}


# Metrik turunan waktu-dinding (std::chrono, pengukuran 3D Cube per entitas): berbeda di
# setiap run walau simulasi identik (terukur di server: hanya dua baris ini yang berbeda
# antara run berulang). Dikecualikan dari kesamaan metrik, tetapi nilainya dilaporkan.
WALLCLOCK_METRICS = ("rt_compute_ms", "computation_overhead_percent")


def _metric_rows(path):
    with open(path) as f:
        lines = f.read().splitlines()
    if not lines or lines[0] != "metric,value":
        raise ValueError(f"{path}: bukan berkas metrik")
    rows = [ln.split(",", 1) for ln in lines[1:] if ln]
    if len({k for k, _ in rows}) != len(rows):
        raise ValueError(f"{path}: metrik duplikat")
    return rows


def identical(path_a, path_b, metrics=False):
    """Byte-identik; untuk berkas metrik (metrics=True) semua baris harus identik kecuali
    WALLCLOCK_METRICS (urutan dan nama baris tetap harus sama)."""
    if not metrics:
        return {"a": path_a, "b": path_b, "mode": "bytes",
                "identical": _read(path_a) == _read(path_b)}
    ra, rb = _metric_rows(path_a), _metric_rows(path_b)
    same_keys = [k for k, _ in ra] == [k for k, _ in rb]
    da, db = dict(ra), dict(rb)
    diff = sorted(k for k in da if k in db and da[k] != db[k] and k not in WALLCLOCK_METRICS)
    wall = {k: {"a": da.get(k), "b": db.get(k)} for k in WALLCLOCK_METRICS}
    return {"a": path_a, "b": path_b, "mode": "metrics_except_wallclock",
            "identical": same_keys and not diff, "same_rows": same_keys,
            "differing_metrics": diff, "wallclock_ignored": wall}


def _hybrid(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def _isolation_counts(rows):
    isolated = [row for row in rows if row["isolate"] == "1"]
    by_dto = sum(row["reason"] in ("dto", "dto+bigan") for row in isolated)
    by_bigan_only = sum(row["reason"] == "bigan" for row in isolated)
    return len(isolated), by_dto, by_bigan_only


def applied(dec_dir, metrics_b, log_b, nodes, seeds):
    """Keputusan berkas (Python) = yang diterapkan C++ di run B (tanpa label)."""
    meta = json.load(open(os.path.join(dec_dir, "hybrid_meta.json")))
    out = []
    for n in nodes:
        for s in seeds:
            tag = f"{n}_s{s}"
            rows = _hybrid(os.path.join(dec_dir, f"hybrid_decisions_{tag}.csv"))
            iso, iso_dto, iso_bigan = _isolation_counts(rows)
            exp = {"ids_mode": 1, "nodes_blocked": iso, "isolated_by_dto": iso_dto,
                   "isolated_by_bigan_only": iso_bigan,
                   "bigan_alarms": sum(r["bigan_pred"] == "1" for r in rows),
                   "reroute_changed": len(meta["scenarios"][tag]["reroute"]["changed_entries"])}
            m = load_metrics(metrics_b.format(tag=tag))
            log = open(log_b.format(tag=tag)).read()
            got = {k: int(m[k]) for k in exp}
            r = {"n": n, "seed": s, "expected": exp, "cpp": got,
                 "log_ok": "[Hybrid IDS]" in log and "sumber keputusan = file" in log,
                 "isolation_transit_drops": int(m["isolation_transit_drops"]),
                 "reroute_unresolved": int(m["reroute_unresolved"])}
            r["pass"] = got == exp and r["log_ok"]
            out.append(r)
    return {"pass": all(r["pass"] for r in out), "scenarios": out}


def same_inputs(dec_dir, telem_dir, nodes, seeds):
    """Telemetry run A baru = telemetry yang dipakai saat dec_dir dibuat (SHA-256 di meta).
    Bila sama, keputusan di dec_dir tetap sah untuk run B binary baru."""
    import hashlib
    meta = json.load(open(os.path.join(dec_dir, "hybrid_meta.json")))
    out = []
    for n in nodes:
        for s in seeds:
            tag = f"{n}_s{s}"
            h = hashlib.sha256(_read(paths(telem_dir, n, s)["links"])).hexdigest()
            out.append({"n": n, "seed": s,
                        "identical": h == meta["scenarios"][tag]["telemetry_links_sha256"]})
    return {"pass": all(r["identical"] for r in out), "scenarios": out}


def evaluate(dec_dir, scenario_dir, metrics_a, metrics_b, nodes, seeds):
    meta = json.load(open(os.path.join(dec_dir, "hybrid_meta.json")))
    agg = {k: {"TP": 0, "FP": 0, "FN": 0, "TN": 0} for k in ("dto", "bigan", "isolate")}
    per, net = [], {m: [] for m in NET_METRICS}
    ins = cov = mal_tot = honest_iso = 0
    path_fail = path_tot = 0
    for n in nodes:
        for s in seeds:
            tag = f"{n}_s{s}"
            rows = _hybrid(os.path.join(dec_dir, f"hybrid_decisions_{tag}.csv"))
            mal, _ = labels(scenario_dir, n, s)          # label: SETELAH keputusan
            dto = np.array([r["dto_decision"] == "malicious" for r in rows])
            insuf = np.array([r["dto_decision"] == "insufficient_evidence" for r in rows])
            big = np.array([r["bigan_pred"] == "1" for r in rows])
            iso = np.array([r["isolate"] == "1" for r in rows])
            sc = {"n": n, "seed": s}
            for k, v in (("dto", dto), ("bigan", big), ("isolate", iso)):
                c = conf(v, mal)
                for kk in c:
                    agg[k][kk] += c[kk]
                sc[k] = scores(c)
            ins += int(insuf.sum())
            cov += int((mal & ~insuf).sum())
            mal_tot += int(mal.sum())
            honest_iso += int((iso & ~mal).sum())
            rep = meta["scenarios"][tag]["reroute"]
            pf = sum(1 for p in rep["paths"] if p["status"] == "failed")
            path_fail += pf
            path_tot += len(rep["paths"])
            sc["reroute"] = {"changed_entries": len(rep["changed_entries"]),
                             "failed_entries": len(rep["failed_entries"]),
                             "failed_paths": pf}
            ma = load_metrics(metrics_a.format(tag=tag)) if metrics_a else None
            mb = load_metrics(metrics_b.format(tag=tag)) if metrics_b else None
            if ma and mb:
                sc["network"] = {m: {"A": ma.get(m), "B": mb.get(m)} for m in NET_METRICS}
                sc["ids_counters_B"] = {m: mb.get(m) for m in IDS_METRICS}
                for m in NET_METRICS:
                    # nan (PDR jujur tidak terdefinisi) tidak dipasangkan
                    if m in ma and m in mb and not (np.isnan(ma[m]) or np.isnan(mb[m])):
                        net[m].append(mb[m] - ma[m])
                for k, mm in (("A", ma), ("B", mb)):
                    if "benign_tx_packets" in mm:
                        exp = benign_pdr(mm["benign_tx_packets"], mm["benign_rx_packets"])
                        got = mm["benign_pdr_percent"]
                        if not ((np.isnan(exp) and np.isnan(got))
                                or abs(exp - got) <= 1e-4 * max(1.0, abs(exp))):
                            raise ValueError(f"{tag} {k}: benign_pdr_percent {got} != "
                                             f"rx/tx {exp}")
            per.append(sc)
    paired = {}
    for m, d in net.items():
        if not d:
            continue
        d = np.array(d)
        entry = {"n_pairs": len(d), "mean_B_minus_A": float(d.mean()),
                 "median_B_minus_A": float(np.median(d)), "B_gt_A": int((d > 0).sum()),
                 "B_lt_A": int((d < 0).sum()), "equal": int((d == 0).sum())}
        if len(d) >= 6 and (d != 0).any():
            from scipy.stats import wilcoxon
            entry["wilcoxon_p"] = float(wilcoxon(d).pvalue)
        paired[m] = entry
    return {"meta_fusion": meta["fusion"], "meta_dto": meta["dto"],
            "detection_at_t_ids": {k: scores(v) for k, v in agg.items()},
            "dto_insufficient_evidence": ins, "dto_coverage_malicious": [cov, mal_tot],
            "honest_isolated": honest_iso, "failed_paths": [path_fail, path_tot],
            "network_paired": paired, "scenarios": per}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("determinism")
    d.add_argument("--dir-a", required=True)
    d.add_argument("--dir-b", required=True)
    i = sub.add_parser("identical")
    i.add_argument("--a", required=True)
    i.add_argument("--b", required=True)
    i.add_argument("--metrics", action="store_true",
                   help="berkas metrik: abaikan hanya baris waktu-dinding (dilaporkan)")
    e = sub.add_parser("evaluate")
    e.add_argument("--dec-dir", required=True)
    e.add_argument("--scenario-dir", required=True)
    e.add_argument("--metrics-a", default=None, help="pola path, mis. dir/metrics_{tag}_A.csv")
    e.add_argument("--metrics-b", default=None)
    ap_ = sub.add_parser("applied")
    ap_.add_argument("--dec-dir", required=True)
    ap_.add_argument("--metrics-b", required=True, help="pola path dgn {tag}")
    ap_.add_argument("--log-b", required=True, help="pola path dgn {tag}")
    si = sub.add_parser("same-inputs")
    si.add_argument("--dec-dir", required=True)
    si.add_argument("--telem-dir", required=True)
    for p in (d, e, ap_, si):
        p.add_argument("--nodes", type=int, nargs="+", required=True)
        p.add_argument("--seeds", type=int, nargs="+", default=[1])
    for p in (d, i, e, ap_, si):
        p.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "determinism":
        res = determinism(a.dir_a, a.dir_b, a.nodes, a.seeds)
    elif a.cmd == "identical":
        res = identical(a.a, a.b, a.metrics)
    elif a.cmd == "applied":
        res = applied(a.dec_dir, a.metrics_b, a.log_b, a.nodes, a.seeds)
    elif a.cmd == "same-inputs":
        res = same_inputs(a.dec_dir, a.telem_dir, a.nodes, a.seeds)
    else:
        res = evaluate(a.dec_dir, a.scenario_dir, a.metrics_a, a.metrics_b, a.nodes, a.seeds)
    txt = json.dumps(res, indent=1)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w") as f:
            f.write(txt)
    print(txt if a.cmd != "evaluate" else json.dumps(
        {k: v for k, v in res.items() if k != "scenarios"}, indent=1))
    ok = res.get("pass", res.get("identical", True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
