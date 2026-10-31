"""
run_analysis.py
Load the Kaggle "2015 Flight Delays and Cancellations" files into SQLite, run the cleaning SQL,
run every named query in sql/02_analysis.sql and save the results to results/*.csv.

Works unchanged on the 3% sample (flights_sample.csv) and on the full flights.csv (5.8M rows):
the file is read in chunks, and the size thresholds in the SQL scale with the number of rows.

Usage:
    python run_analysis.py data/flights.csv
    python run_analysis.py data/flights_sample.csv

Expects airlines.csv and airports.csv in data/ (or pass --airlines / --airports).
"""
import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
DB_PATH = DATA / "flights.db"
RAW_DB_PATH = DATA / "flights_raw.db"  # temporary: raw text copy, deleted after cleaning

FULL_ROWS = 5_819_079  # rows in the full Kaggle file; thresholds are written for this size

# Columns kept from the CSV (everything else, e.g. taxi times, is not used)
RAW_COLUMNS = [
    "YEAR", "MONTH", "DAY", "DAY_OF_WEEK", "AIRLINE", "FLIGHT_NUMBER",
    "ORIGIN_AIRPORT", "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE",
    "DEPARTURE_DELAY", "DISTANCE", "ARRIVAL_DELAY", "DIVERTED", "CANCELLED",
    "CANCELLATION_REASON", "AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY",
    "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY",
]
CHUNK_ROWS = 250_000


def thresholds(n_rows: int) -> dict:
    """Size thresholds written for the full file, scaled down for a sample."""
    scale = min(1.0, n_rows / FULL_ROWS)
    return {
        "scale": round(scale, 5),
        "min_side": max(1, round(20 * scale)),         # completed flights per side in a route-month cell
        "min_airport": max(50, round(10_000 * scale)),  # departures for an airport to be listed
        "min_route": max(50, round(5_000 * scale)),     # flights for a route to be listed
    }


def load_raw(csv_path: Path) -> int:
    """Stream the CSV into a temporary SQLite file as untouched text."""
    if RAW_DB_PATH.exists():
        RAW_DB_PATH.unlink()
    con = sqlite3.connect(RAW_DB_PATH)
    con.execute("PRAGMA journal_mode = OFF")
    con.execute("PRAGMA synchronous = OFF")
    con.execute("CREATE TABLE raw_flights (" + ", ".join(f'"{c}" TEXT' for c in RAW_COLUMNS) + ")")
    insert = f"INSERT INTO raw_flights VALUES ({','.join('?' * len(RAW_COLUMNS))})"

    total = 0
    reader = pd.read_csv(
        csv_path, usecols=RAW_COLUMNS, dtype=str, keep_default_na=False, chunksize=CHUNK_ROWS
    )
    for chunk in reader:
        con.executemany(insert, chunk[RAW_COLUMNS].values.tolist())
        total += len(chunk)
        print(f"  loaded {total:,} rows", end="\r", flush=True)
    con.commit()
    con.close()
    print(f"  loaded {total:,} rows")
    return total


def split_queries(sql_text: str) -> dict:
    """Split a SQL file into {name: query} using '-- name: <id>' marker lines."""
    parts = re.split(r"^-- name:\s*(\S+)\s*$", sql_text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def peak_memory_mb():
    try:
        import resource  # not available on Windows

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(usage / 1024 / (1024 if usage > 10**9 else 1), 0)  # Linux: KB, macOS: bytes
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("flights_csv")
    ap.add_argument("--airlines", default=str(DATA / "airlines.csv"))
    ap.add_argument("--airports", default=str(DATA / "airports.csv"))
    ap.add_argument("--keep-raw", action="store_true", help="keep the temporary raw copy")
    args = ap.parse_args()

    for label, path in (("flights CSV", args.flights_csv), ("airlines.csv", args.airlines),
                        ("airports.csv", args.airports)):
        if not Path(path).exists():
            raise SystemExit(f"Cannot find {label} at '{path}'. Download the three files from Kaggle "
                             f"('2015 Flight Delays and Cancellations') and put them in the data/ folder.")
    t0 = time.time()
    timings = {}
    RESULTS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # always rebuild from scratch

    print("1/4 loading CSV in chunks ...")
    t = time.time()
    n_rows = load_raw(Path(args.flights_csv))
    timings["load_s"] = round(time.time() - t, 1)
    params = thresholds(n_rows)
    if n_rows < FULL_ROWS * 0.9:
        print(f"  NOTE: {n_rows:,} rows is a sample of the full file ({FULL_ROWS:,}); "
              f"thresholds scaled by {params['scale']}. Use the full file for final numbers.")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA temp_store = FILE")
    con.execute("PRAGMA cache_size = -400000")  # ~400 MB page cache
    con.execute(f"ATTACH DATABASE '{RAW_DB_PATH.as_posix()}' AS raw")

    for name, path in (("airlines", args.airlines), ("airports", args.airports)):
        pd.read_csv(path, keep_default_na=False).to_sql(name, con, if_exists="replace", index=False)

    print("2/4 cleaning (airport-ID map, typed table, flags) ...")
    t = time.time()
    con.executescript((ROOT / "sql" / "01_clean.sql").read_text(encoding="utf-8"))
    con.commit()
    timings["clean_s"] = round(time.time() - t, 1)
    n_clean = con.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    print(f"  raw rows: {n_rows:,} | flights table: {n_clean:,}")

    print("3/4 running analysis queries ...")
    t = time.time()
    queries = split_queries((ROOT / "sql" / "02_analysis.sql").read_text(encoding="utf-8"))
    for name, query in queries.items():
        df = pd.read_sql_query(query, con, params=params)
        df.to_csv(RESULTS / f"{name}.csv", index=False)
        print(f"\n=== {name} ({len(df)} rows) ===")
        print(df.head(25).to_string(index=False))
    timings["analysis_s"] = round(time.time() - t, 1)

    con.execute("DETACH DATABASE raw")
    con.close()
    if not args.keep_raw and RAW_DB_PATH.exists():
        RAW_DB_PATH.unlink()

    timings["total_s"] = round(time.time() - t0, 1)
    info = {
        "input_file": Path(args.flights_csv).name,
        "rows_loaded": n_rows,
        "full_file_rows": FULL_ROWS,
        "is_full_file": n_rows >= FULL_ROWS * 0.9,
        "thresholds": params,
        "timings_seconds": timings,
        "peak_memory_mb": peak_memory_mb(),
        "db_size_mb": round(DB_PATH.stat().st_size / 1e6, 0),
    }
    (RESULTS / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"\n4/4 done in {timings['total_s']}s -> results/*.csv, results/run_info.json")


if __name__ == "__main__":
    main()
