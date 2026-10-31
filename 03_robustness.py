"""
03_robustness.py
How much should we trust the "fair" airline comparison (q06 in sql/02_analysis.sql)?

1. Confidence intervals: a cluster bootstrap that resamples whole airport PAIRS (A-B and B-A together),
   because flights on the same route share weather, congestion and airports, so they are not independent.
2. Sensitivity: the same comparison under different choices (finer cells, stricter minimum, a 30-minute
   lateness threshold, without October whose airport codes had to be reconstructed, first vs second half-year).

Reads the small cell_airline table from data/flights.db (made by run_analysis.py).
Writes results/r01_fair_ci.csv, r02_sensitivity.csv, r03_rank_agreement.csv.

Usage: python 03_robustness.py
"""
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "flights.db"
RESULTS = ROOT / "results"
N_BOOT = 1000
SEED = 2015

CELL_KEYS = ["month", "origin_key", "dest_key"]  # the main comparison: same route, same month


def load_cells() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    cells = pd.read_sql_query("SELECT * FROM cell_airline", con)
    con.close()
    a, b = cells["origin_key"], cells["dest_key"]
    cells["pair"] = np.where(a < b, a + "|" + b, b + "|" + a)  # A->B and B->A form one cluster
    return cells


def cell_terms(cells: pd.DataFrame, keys: list, min_side: int, late_col: str = "n_late") -> pd.DataFrame:
    """One row per (cell, airline) that has at least min_side flights for the airline AND for all others.
    own_* = the airline's counts; exp_* = what the airline would have had at the others' rate."""
    g = cells.groupby(keys + ["airline", "pair"], as_index=False)[
        ["n_sched", "n_completed", late_col, "n_problem"]
    ].sum()
    g = g.rename(columns={late_col: "late", "n_completed": "comp", "n_sched": "sched", "n_problem": "prob"})
    for c in ["sched", "comp", "late", "prob"]:
        g["o_" + c] = g.groupby(keys)[c].transform("sum") - g[c]
    g = g[(g["comp"] >= min_side) & (g["o_comp"] >= min_side)].copy()
    g["exp_late"] = g["comp"] * g["o_late"] / g["o_comp"]
    g["exp_prob"] = g["sched"] * g["o_prob"] / g["o_sched"]
    return g


def estimate(terms: pd.DataFrame, total_comp: pd.Series) -> pd.DataFrame:
    a = terms.groupby("airline")[["comp", "late", "exp_late", "sched", "prob", "exp_prob"]].sum()
    out = pd.DataFrame({
        "comparable_flights": a["comp"],
        "coverage_pct": 100 * a["comp"] / total_comp.reindex(a.index),
        "diff_late_pp": 100 * (a["late"] - a["exp_late"]) / a["comp"],
        "diff_problem_pp": 100 * (a["prob"] - a["exp_prob"]) / a["sched"],
    })
    out["rank_late"] = out["diff_late_pp"].rank(method="min").astype(int)
    return out


def cluster_bootstrap(terms: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """95% intervals for diff_late_pp and diff_problem_pp, resampling airport pairs."""
    pairs = np.sort(terms["pair"].unique())
    airlines = np.sort(terms["airline"].unique())
    p_idx = pd.Series(np.arange(len(pairs)), index=pairs)
    a_idx = pd.Series(np.arange(len(airlines)), index=airlines)

    agg = terms.groupby(["pair", "airline"], as_index=False)[
        ["comp", "late", "exp_late", "sched", "prob", "exp_prob"]
    ].sum()
    pi, ai = p_idx[agg["pair"]].to_numpy(), a_idx[agg["airline"]].to_numpy()

    def mat(col):
        m = np.zeros((len(pairs), len(airlines)))
        m[pi, ai] = agg[col].to_numpy()
        return m

    comp, late, exp_late = mat("comp"), mat("late"), mat("exp_late")
    sched, prob, exp_prob = mat("sched"), mat("prob"), mat("exp_prob")

    late_diffs, prob_diffs = [], []
    for start in range(0, N_BOOT, 100):  # batches keep memory small
        counts = rng.multinomial(len(pairs), np.full(len(pairs), 1 / len(pairs)), size=100).astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            late_diffs.append(100 * (counts @ late - counts @ exp_late) / (counts @ comp))
            prob_diffs.append(100 * (counts @ prob - counts @ exp_prob) / (counts @ sched))
    late_diffs, prob_diffs = np.vstack(late_diffs), np.vstack(prob_diffs)

    out = pd.DataFrame({
        "airport_pairs": (comp > 0).sum(axis=0),
        "late_lo": np.nanpercentile(late_diffs, 2.5, axis=0),
        "late_hi": np.nanpercentile(late_diffs, 97.5, axis=0),
        "problem_lo": np.nanpercentile(prob_diffs, 2.5, axis=0),
        "problem_hi": np.nanpercentile(prob_diffs, 97.5, axis=0),
    }, index=airlines)
    return out


def main() -> None:
    t0 = time.time()
    info = json.loads((RESULTS / "run_info.json").read_text())
    m = info["thresholds"]["min_side"]
    print(f"input: {info['input_file']} ({info['rows_loaded']:,} rows), min_side = {m}")
    if not info["is_full_file"]:
        print("NOTE: sample run - intervals will be wide; use the full file for final numbers.")

    cells = load_cells()
    total_comp = cells.groupby("airline")["n_completed"].sum()
    rng = np.random.default_rng(SEED)

    # ---- 1) main estimate + bootstrap intervals
    main_terms = cell_terms(cells, CELL_KEYS, m)
    main_est = estimate(main_terms, total_comp)
    ci = cluster_bootstrap(main_terms, rng)
    r01 = main_est.join(ci)
    r01["late_clear"] = np.where(r01["late_hi"] < 0, "better than others",
                          np.where(r01["late_lo"] > 0, "worse than others", "not clearly different"))
    r01["problem_clear"] = np.where(r01["problem_hi"] < 0, "better than others",
                            np.where(r01["problem_lo"] > 0, "worse than others", "not clearly different"))
    r01 = r01.round(2).sort_values("diff_late_pp").rename_axis("airline").reset_index()
    r01.to_csv(RESULTS / "r01_fair_ci.csv", index=False)
    print("\n=== r01_fair_ci ===")
    print(r01.to_string(index=False))

    # ---- 2) sensitivity to analysis choices
    specs = {
        "main: same route + month": dict(keys=CELL_KEYS, min_side=m, cells=cells, late="n_late"),
        "finer: route + month + time of day": dict(keys=CELL_KEYS + ["daypart"], min_side=m, cells=cells, late="n_late"),
        "stricter: 2.5x minimum flights per side": dict(keys=CELL_KEYS, min_side=int(np.ceil(2.5 * m)), cells=cells, late="n_late"),
        "late = 30+ min instead of 15+": dict(keys=CELL_KEYS, min_side=m, cells=cells, late="n_late30"),
        "without October (rebuilt airport codes)": dict(keys=CELL_KEYS, min_side=m, cells=cells[cells["month"] != 10], late="n_late"),
        "first half-year (Jan-Jun)": dict(keys=CELL_KEYS, min_side=m, cells=cells[cells["month"] <= 6], late="n_late"),
        "second half-year (Jul-Dec)": dict(keys=CELL_KEYS, min_side=m, cells=cells[cells["month"] >= 7], late="n_late"),
    }
    rows = []
    for name, s in specs.items():
        sub = s["cells"]
        est = estimate(cell_terms(sub, s["keys"], s["min_side"], s["late"]),
                       sub.groupby("airline")["n_completed"].sum())
        est.insert(0, "spec", name)
        rows.append(est.reset_index().rename(columns={"index": "airline"}))
    r02 = pd.concat(rows, ignore_index=True).round(2)
    r02.to_csv(RESULTS / "r02_sensitivity.csv", index=False)

    # ---- 3) do the rankings agree with the main one?
    base = r02[r02["spec"] == list(specs)[0]].set_index("airline")["diff_late_pp"]
    agree = []
    for name in specs:
        cur = r02[r02["spec"] == name].set_index("airline")["diff_late_pp"]
        common = base.index.intersection(cur.index)
        agree.append({
            "spec": name,
            "airlines_compared": len(common),
            "rank_correlation_with_main": round(base[common].rank().corr(cur[common].rank()), 3),
            "same_sign_as_main": int((np.sign(base[common]) == np.sign(cur[common])).sum()),
        })
    r03 = pd.DataFrame(agree)
    r03.to_csv(RESULTS / "r03_rank_agreement.csv", index=False)
    print("\n=== r03_rank_agreement ===")
    print(r03.to_string(index=False))
    print(f"\ndone in {time.time() - t0:.1f}s -> results/r01_fair_ci.csv, r02_sensitivity.csv, r03_rank_agreement.csv")


if __name__ == "__main__":
    main()
