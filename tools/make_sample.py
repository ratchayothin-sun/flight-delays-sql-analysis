"""
make_sample.py
flights.csv (about 565 MB, 5.8 million rows) is too big to attach to a chat. This script reads it
in chunks and writes two small files:

  flights_sample.csv     a random sample of rows (default 3%), copied as raw text, same columns
  flights_profile.json   a summary of the FULL file: row counts, empty values per column,
                         airport-code formats, cancellations, which delay-cause columns are filled

Attach both files to the chat. Nothing is changed or uploaded by this script.

Usage:
    python make_sample.py path/to/flights.csv            (3% sample)
    python make_sample.py path/to/flights.csv 0.05       (5% sample)

The two output files are written to the folder you run the command from.
Needs only pandas:  pip install pandas
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

CHUNK = 250_000
SEED = 2015
CAUSE_COLS = ["AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY", "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY"]
EXPECTED = [
    "YEAR", "MONTH", "DAY", "DAY_OF_WEEK", "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER", "ORIGIN_AIRPORT",
    "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE", "DEPARTURE_TIME", "DEPARTURE_DELAY", "TAXI_OUT",
    "WHEELS_OFF", "SCHEDULED_TIME", "ELAPSED_TIME", "AIR_TIME", "DISTANCE", "WHEELS_ON", "TAXI_IN",
    "SCHEDULED_ARRIVAL", "ARRIVAL_TIME", "ARRIVAL_DELAY", "DIVERTED", "CANCELLED", "CANCELLATION_REASON",
] + CAUSE_COLS


def code_format(s: pd.Series) -> dict:
    """How many airport codes look like 'ATL' (three letters), like '10397' (digits only), other, empty."""
    empty = (s == "").sum()
    letters = s.str.fullmatch(r"[A-Za-z]{3}").sum()
    digits = s.str.fullmatch(r"[0-9]+").sum()
    return {"three_letters": int(letters), "digits_only": int(digits),
            "other": int(len(s) - empty - letters - digits), "empty": int(empty)}


def add_counts(total: Counter, series: pd.Series) -> None:
    total.update({str(k): int(v) for k, v in series.value_counts().items()})


def main(path: str, fraction: float) -> None:
    src = Path(path)
    out_sample, out_profile = Path("flights_sample.csv").resolve(), Path("flights_profile.json").resolve()

    rows = 0
    columns = None
    nulls = Counter()
    year, month, airline = Counter(), Counter(), Counter()
    cancelled, diverted, reason = Counter(), Counter(), Counter()
    fmt_origin, fmt_dest = Counter(), Counter()
    digit_origin_by_month, top_digit_origin = Counter(), Counter()
    letter_origin_codes = set()
    delay = {"count": 0, "sum": 0.0, "min": None, "max": None, "negative": 0, "ge15": 0}
    cause = {c: Counter() for c in CAUSE_COLS}
    cancelled_with_delay = diverted_with_delay = 0

    reader = pd.read_csv(src, dtype=str, keep_default_na=False, chunksize=CHUNK)
    for i, chunk in enumerate(reader):
        if columns is None:
            columns = list(chunk.columns)
        rows += len(chunk)
        chunk.sample(frac=fraction, random_state=SEED + i).sort_index().to_csv(
            out_sample, mode="a" if i else "w", header=(i == 0), index=False)

        for c in chunk.columns:
            nulls[c] += int((chunk[c] == "").sum())
        for name, counter in [("YEAR", year), ("MONTH", month), ("AIRLINE", airline),
                              ("CANCELLED", cancelled), ("DIVERTED", diverted),
                              ("CANCELLATION_REASON", reason)]:
            if name in chunk.columns:
                add_counts(counter, chunk[name])

        if "ORIGIN_AIRPORT" in chunk.columns:
            o = chunk["ORIGIN_AIRPORT"]
            fmt_origin.update(code_format(o))
            is_digit = o.str.fullmatch(r"[0-9]+")
            if "MONTH" in chunk.columns:
                digit_origin_by_month.update({str(k): int(v) for k, v in chunk.loc[is_digit, "MONTH"].value_counts().items()})
            top_digit_origin.update({str(k): int(v) for k, v in o[is_digit].value_counts().items()})
            letter_origin_codes.update(o[o.str.fullmatch(r"[A-Za-z]{3}")].unique())
        if "DESTINATION_AIRPORT" in chunk.columns:
            fmt_dest.update(code_format(chunk["DESTINATION_AIRPORT"]))

        if "ARRIVAL_DELAY" in chunk.columns:
            ad = pd.to_numeric(chunk["ARRIVAL_DELAY"], errors="coerce")
            ok = ad.dropna()
            if len(ok):
                delay["count"] += int(len(ok))
                delay["sum"] += float(ok.sum())
                delay["min"] = float(ok.min()) if delay["min"] is None else min(delay["min"], float(ok.min()))
                delay["max"] = float(ok.max()) if delay["max"] is None else max(delay["max"], float(ok.max()))
                delay["negative"] += int((ok < 0).sum())
                delay["ge15"] += int((ok >= 15).sum())
            if "CANCELLED" in chunk.columns:
                cancelled_with_delay += int(((chunk["CANCELLED"] == "1") & ad.notna()).sum())
            if "DIVERTED" in chunk.columns:
                diverted_with_delay += int(((chunk["DIVERTED"] == "1") & ad.notna()).sum())
            late, notlate = ad >= 15, ad < 15
            for c in CAUSE_COLS:
                if c in chunk.columns:
                    present = chunk[c] != ""
                    cause[c].update({
                        "filled_when_delay_15_plus": int((present & late).sum()),
                        "empty_when_delay_15_plus": int((~present & late).sum()),
                        "filled_when_delay_under_15": int((present & notlate).sum()),
                    })
        print(f"  {rows:>10,} rows read", end="\r", flush=True)

    profile = {
        "file": src.name,
        "rows": rows,
        "sample_fraction": fraction,
        "columns": columns,
        "missing_expected_columns": [c for c in EXPECTED if c not in (columns or [])],
        "extra_columns": [c for c in (columns or []) if c not in EXPECTED],
        "empty_values_per_column": dict(nulls),
        "year_counts": dict(year),
        "month_counts": dict(sorted(month.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 99)),
        "airline_counts": dict(airline),
        "origin_airport_code_formats": dict(fmt_origin),
        "destination_airport_code_formats": dict(fmt_dest),
        "rows_with_digit_only_origin_code_by_month": dict(digit_origin_by_month),
        "most_common_digit_only_origin_codes": dict(top_digit_origin.most_common(15)),
        "distinct_three_letter_origin_codes": sorted(letter_origin_codes),
        "cancelled_counts": dict(cancelled),
        "diverted_counts": dict(diverted),
        "cancellation_reason_counts": dict(reason),
        "arrival_delay_minutes": {
            "rows_with_a_value": delay["count"],
            "mean": round(delay["sum"] / delay["count"], 4) if delay["count"] else None,
            "min": delay["min"], "max": delay["max"],
            "negative_values": delay["negative"], "values_15_or_more": delay["ge15"],
        },
        "cancelled_flights_that_still_have_an_arrival_delay": cancelled_with_delay,
        "diverted_flights_that_still_have_an_arrival_delay": diverted_with_delay,
        "delay_cause_columns_vs_arrival_delay": {c: dict(v) for c, v in cause.items()},
    }
    with open(out_profile, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    n_sample = sum(1 for _ in open(out_sample, encoding="utf-8")) - 1
    print(f"\nDone. {rows:,} rows read.")
    print(f"  sample : {out_sample}  ({n_sample:,} rows, {out_sample.stat().st_size / 1e6:.1f} MB)")
    print(f"  profile: {out_profile}  ({out_profile.stat().st_size / 1e3:.1f} KB)")
    print("Attach both files to the chat.")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: python make_sample.py path/to/flights.csv [fraction, default 0.03]")
    frac = float(sys.argv[2]) if len(sys.argv) == 3 else 0.03
    if not 0 < frac <= 1:
        sys.exit("fraction must be between 0 and 1")
    main(sys.argv[1], frac)
