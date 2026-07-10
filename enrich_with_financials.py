"""
enrich_with_financials.py

Joins the ONRC candidate list (output of filter_romania_startups.py) with
the MFP 2024 annual financial statements (WEB_BL_BS_SL_AN2024.txt) by CUI,
adds employee count and revenue, and filters to companies with at least
MIN_SALARIATI employees.

COLUMN MAPPING for WEB_BL_BS_SL_AN2024.txt (confirmed from .csv spec):
  CUI   -> company tax ID (join key)
  CAEN  -> primary CAEN code for fiscal year
  i1    -> Active imobilizate total
  i2    -> Active circulante total
  i3    -> Stocuri
  i4    -> Creante
  i5    -> Casa si conturi la banci
  i6    -> Cheltuieli in avans
  i7    -> Datorii
  i8    -> Venituri in avans
  i9    -> Provizioane
  i10   -> Capitaluri total
  i11   -> Capital subscris varsat
  i12   -> Patrimoniul regiei
  i13   -> Cifra de afaceri neta  *** REVENUE ***
  i14   -> Venituri totale
  i15   -> Cheltuieli totale
  i16   -> Profit brut
  i17   -> Pierdere bruta
  i18   -> Profit net
  i19   -> Pierdere neta
  i20   -> Numar mediu de salariati  *** EMPLOYEES ***

USAGE:
  python enrich_with_financials.py \
      --candidates candidates_2024plus.csv \
      --financials WEB_BL_BS_SL_AN2024.txt \
      --min-employees 3 \
      --out candidates_enriched.csv

NOTE: Companies registered in late 2024 or 2025/2026 may not appear in the
2024 financial data (they either didn't exist yet or hadn't filed). These are
kept in the output but marked as UNMATCHED with empty financial columns --
they are NOT dropped, so you can decide how to handle them downstream.
"""

import argparse
import sys
import pandas as pd

ONRC_DELIM = "^"
MFP_DELIM = ","

# Columns to carry forward from the MFP file
MFP_COLS = {
    "CUI": "CUI",
    "CAEN": "CAEN_MFP",
    "i13": "CIFRA_AFACERI",
    "i14": "VENITURI_TOTALE",
    "i18": "PROFIT_NET",
    "i20": "NR_SALARIATI",
}


def load_financials(path: str) -> pd.DataFrame:
    print("Loading MFP financial data...", file=sys.stderr)

    # The .txt file uses comma delimiter and has a header row
    # with column names CUI,CAEN,I1,...,I20 (case may vary)
    df = pd.read_csv(
        path, sep=MFP_DELIM, dtype=str,
        encoding="utf-8", keep_default_na=False,
    )

    # Normalize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    # Rename to friendly names, keeping only what we need
    rename_map = {k.lower(): v for k, v in MFP_COLS.items()}
    df = df.rename(columns=rename_map)
    keep = list(rename_map.values())
    df = df[[c for c in keep if c in df.columns]]

    # Normalize CUI: strip whitespace, remove leading zeros for matching
    df["CUI"] = df["CUI"].str.strip()

    # Convert numeric columns
    for col in ["CIFRA_AFACERI", "VENITURI_TOTALE", "PROFIT_NET", "NR_SALARIATI"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"  -> {len(df):,} companies in MFP financial data", file=sys.stderr)
    return df


def load_candidates(path: str) -> pd.DataFrame:
    print("Loading ONRC candidates...", file=sys.stderr)
    df = pd.read_csv(
        path, sep=ONRC_DELIM, dtype=str,
        encoding="utf-8", keep_default_na=False,
        engine="python", on_bad_lines="warn",
    )
    df.columns = [c.strip() for c in df.columns]

    # Normalize CUI for joining
    df["CUI"] = df["CUI"].str.strip()

    print(f"  -> {len(df):,} candidates loaded", file=sys.stderr)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", required=True,
                    help="Output of filter_romania_startups.py (candidates CSV)")
    ap.add_argument("--financials", required=True,
                    help="WEB_BL_BS_SL_AN2024.txt from MFP")
    ap.add_argument("--min-employees", type=int, default=3,
                    help="Minimum NR_SALARIATI to keep (default: 3)")
    ap.add_argument("--out", required=True,
                    help="Output enriched CSV path")
    args = ap.parse_args()

    candidates = load_candidates(args.candidates)
    financials = load_financials(args.financials)

    print("Joining on CUI...", file=sys.stderr)
    merged = candidates.merge(financials, on="CUI", how="left")

    total = len(merged)
    matched = merged["NR_SALARIATI"].notna().sum()
    unmatched = total - matched
    print(f"  -> {matched:,} candidates matched to financial data", file=sys.stderr)
    print(f"  -> {unmatched:,} candidates unmatched (too new or not filed yet)",
          file=sys.stderr)

    # Filter: keep companies with >= min_employees OR unmatched ones
    # (unmatched = likely 2025/2026 registrations, too new to have filed)
    has_enough = merged["NR_SALARIATI"] >= args.min_employees
    is_unmatched = merged["NR_SALARIATI"].isna()

    # Add a status column so you can see at a glance in the output
    merged["ENRICHMENT_STATUS"] = "unmatched"
    merged.loc[has_enough, "ENRICHMENT_STATUS"] = "verified"
    merged.loc[
        merged["NR_SALARIATI"].notna() & ~has_enough,
        "ENRICHMENT_STATUS"
    ] = "below_threshold"

    verified = has_enough.sum()
    below = (merged["NR_SALARIATI"].notna() & ~has_enough).sum()
    print(f"\nResults:", file=sys.stderr)
    print(f"  verified (>= {args.min_employees} employees): {verified:,}", file=sys.stderr)
    print(f"  below threshold (matched, < {args.min_employees} employees): {below:,}",
          file=sys.stderr)
    print(f"  unmatched (no 2024 filing found): {unmatched:,}", file=sys.stderr)

    # Write all rows with status column — let the user decide what to filter
    merged.to_csv(args.out, sep=ONRC_DELIM, index=False, encoding="utf-8")
    print(f"\n  -> {len(merged):,} total rows written to {args.out}", file=sys.stderr)
    print(f"     Filter on ENRICHMENT_STATUS='verified' for the clean set",
          file=sys.stderr)


if __name__ == "__main__":
    main()
