"""
filter_romania_startups.py

Filters the ONRC bulk open-data export (data.gov.ro) down to a candidate list
of recently-registered, active, tech/R&D-flagged SRL/SA companies in Romania.

This is STAGE 1 of the pipeline: registry-only filtering. It does NOT determine
whether a company is a "real" startup vs. a 1-person shell -- that requires
external enrichment (LinkedIn, job postings, web presence), which is stage 2.

INPUT FILES (download from https://data.gov.ro/organization/onrc):
  - OD_FIRME.csv              (company identity, address, legal form, reg. date)
  - OD_STARE_FIRMA.csv        (status events, keyed by COD_INMATRICULARE)
  - OD_CAEN_AUTORIZAT.csv     (CAEN activity codes, keyed by COD_INMATRICULARE)
  - nomenclator CAEN file     (CAEN code -> description, all versions 0-3)

All files use '^' as the delimiter. Join key across files is COD_INMATRICULARE
(the J-number), NOT CUI.

USAGE:
  python filter_romania_startups.py \
      --firme OD_FIRME.csv \
      --stare OD_STARE_FIRMA.csv \
      --caen_autorizat OD_CAEN_AUTORIZAT.csv \
      --nomenclator nomenclator_caen.csv \
      --from-date 2025-01-01 \
      --to-date 2026-06-30 \
      --out candidates.csv

NOTES / ASSUMPTIONS (read before trusting the output):
  1. OD_STARE_FIRMA has no date/ordering column in the published export, so we
     cannot determine the LATEST status chronologically. Instead, a company is
     marked inactive if a terminal status code (radiata, faliment, lichidare,
     dizolvare...) appears ANYWHERE in its status history. This is a safe-ish
     proxy but can mislabel a company that dissolved and somehow re-registered
     under the same J-number (rare). Verify a sample manually before trusting
     this at scale.
  2. Tech/R&D relevance is determined by keyword-matching the CAEN nomenclature
     descriptions (informatica, software, cercetare-dezvoltare, telecomunicatii,
     etc.) rather than hardcoding class codes -- this is more robust across the
     four CAEN revisions (0/1/2/3) mixed in the data than maintaining a manual
     code list, but it WILL pull in some adjacent categories (e.g. telecom
     infrastructure). Review and tighten KEYWORDS below for your needs.
  3. Files are large (the Dec-2025 OD_FIRME snapshot is ~675MB), so this script
     reads in chunks and never loads the full file into memory at once.
"""

import argparse
import sys
import unicodedata
import pandas as pd

DELIM = "^"

# Status codes (from the nomenclature you provided) that indicate the company
# is no longer active. Extend this list if you find others worth excluding.
TERMINAL_STATUS_CODES = {
    "1084",  # radiata (deregistered/struck off)
    "1070",  # faliment (bankruptcy)
    "1052",  # lichidare (liquidation)
    "1049",  # dizolvare (dissolution)
    "1109", "1111", "1113", "1120",  # various dizolvare de drept / judiciara
}

# Explicit CAEN code allowlist by category.
# Includes both CAEN Rev.3 (current) and Rev.2 equivalents since
# OD_CAEN_AUTORIZAT mixes both versions depending on when the company filed.
# To add/remove categories, edit the sets below and rerun the pipeline.

CAEN_CATEGORIES = {
    "product_publishing": {
        "5821",  # Rev.3: Editare jocuri de calculator
        "5829",  # Rev.3: Editare alte produse software
        "7221",  # Rev.2 equivalent: Editare de programe
        "7222",  # Rev.2 equivalent: Consultanta si furnizare alte produse software
    },
    "programming_consultancy": {
        "6201",  # Rev.3: Realizarea soft-ului la comanda
        "6202",  # Rev.3: Consultanta in tehnologia informatiei
        "6203",  # Rev.3: Management a mijloacelor de calcul
        "6209",  # Rev.3: Alte servicii privind tehnologia informatiei
        "7210",  # Rev.2 equivalent: Consultanta echipamente de calcul
        "7220",  # Rev.2 equivalent: Realizarea si furnizarea de programe
        "7260",  # Rev.2 equivalent: Alte activitati legate de informatica
    },
    "data_infrastructure": {
        "6311",  # Rev.3: Prelucrarea datelor, administrarea paginilor web
        "6312",  # Rev.3: Activitati ale portalurilor web
        "7230",  # Rev.2 equivalent: Prelucrarea datelor
        "7240",  # Rev.2 equivalent: Activitati legate de bancile de date
    },
}

# Flat set of all allowed codes for fast lookup
ALLOWED_CAEN_CODES = {
    code for codes in CAEN_CATEGORIES.values() for code in codes
}

LEGAL_FORMS_KEEP = {"SRL", "SA"}


def get_tech_inmatriculare_codes(caen_autorizat_path: str) -> tuple:
    """Return (set of matching COD_INMATRICULARE, dict of code->category)."""
    result = set()
    code_to_category = {}
    reader = pd.read_csv(
        caen_autorizat_path, sep=DELIM, dtype=str, chunksize=200_000,
        encoding="utf-8", keep_default_na=False,
    )
    for chunk in reader:
        chunk = chunk.rename(columns=lambda c: c.strip())
        codes = chunk["COD_CAEN_AUTORIZAT"].str.strip()
        mask = codes.isin(ALLOWED_CAEN_CODES)
        result.update(chunk.loc[mask, "COD_INMATRICULARE"])
        # Track which category each J-number belongs to
        for _, row in chunk[mask].iterrows():
            code = row["COD_CAEN_AUTORIZAT"].strip()
            for cat, codes_set in CAEN_CATEGORIES.items():
                if code in codes_set:
                    code_to_category[row["COD_INMATRICULARE"]] = cat
                    break
    return result, code_to_category


def get_inactive_inmatriculare_codes(stare_firma_path: str) -> set:
    """Return COD_INMATRICULARE that have ever had a terminal status code."""
    result = set()
    reader = pd.read_csv(
        stare_firma_path, sep=DELIM, dtype=str, chunksize=500_000,
        encoding="utf-8", keep_default_na=False,
    )
    for chunk in reader:
        chunk = chunk.rename(columns=lambda c: c.strip())
        mask = chunk["COD"].str.strip().isin(TERMINAL_STATUS_CODES)
        result.update(chunk.loc[mask, "COD_INMATRICULARE"])
    return result


def filter_firme(
    firme_path: str,
    tech_codes: set,
    inactive_codes: set,
    from_date: pd.Timestamp,
    to_date: pd.Timestamp,
    out_path: str,
    code_to_category: dict,
):
    wrote_header = False
    total_kept = 0
    reader = pd.read_csv(
        firme_path, sep=DELIM, dtype=str, chunksize=200_000,
        encoding="utf-8", keep_default_na=False,
    )
    for chunk in reader:
        chunk = chunk.rename(columns=lambda c: c.strip())

        # Legal form filter
        chunk = chunk[chunk["FORMA_JURIDICA"].str.strip().isin(LEGAL_FORMS_KEEP)]
        if chunk.empty:
            continue

        # Date filter - handles both DD/MM/YYYY and DD/MM/YYYY HH:MM:SS formats
        raw = chunk["DATA_INMATRICULARE"].str.strip()
        dates = pd.to_datetime(raw, format="%d/%m/%Y", errors="coerce")
        still_missing = dates.isna() & (raw != "")
        if still_missing.any():
            dates.loc[still_missing] = pd.to_datetime(
                raw[still_missing], format="%d/%m/%Y %H:%M:%S", errors="coerce"
            )
        chunk = chunk[(dates >= from_date) & (dates <= to_date)]
        if chunk.empty:
            continue

        # Tech CAEN filter
        chunk = chunk[chunk["COD_INMATRICULARE"].isin(tech_codes)]
        if chunk.empty:
            continue

        # Active-only filter
        chunk = chunk[~chunk["COD_INMATRICULARE"].isin(inactive_codes)]
        if chunk.empty:
            continue

        # Add category column
        chunk["CAEN_CATEGORY"] = chunk["COD_INMATRICULARE"].map(
            lambda x: code_to_category.get(x, "")
        )

        chunk.to_csv(
            out_path, mode="a", index=False,
            header=not wrote_header, sep=DELIM,
        )
        wrote_header = True
        total_kept += len(chunk)

    return total_kept


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--firme", required=True, help="Path to OD_FIRME.csv")
    ap.add_argument("--stare", required=True, help="Path to OD_STARE_FIRMA.csv")
    ap.add_argument("--caen_autorizat", required=True, help="Path to OD_CAEN_AUTORIZAT.csv")
    # --nomenclator no longer needed (replaced by explicit CAEN code allowlist above)
    ap.add_argument("--from-date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to-date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True, help="Output CSV path")
    args = ap.parse_args()

    from_date = pd.Timestamp(args.from_date)
    to_date = pd.Timestamp(args.to_date)

    print("Step 1/4: matching CAEN codes to allowlist categories...", file=sys.stderr)
    for cat, codes in CAEN_CATEGORIES.items():
        print(f"  {cat}: {sorted(codes)}", file=sys.stderr)

    print("Step 2/4: scanning OD_CAEN_AUTORIZAT for matching companies...", file=sys.stderr)
    tech_codes, code_to_category = get_tech_inmatriculare_codes(args.caen_autorizat)
    print(f"  -> {len(tech_codes)} companies with at least one matching CAEN code", file=sys.stderr)

    print("Step 3/4: scanning OD_STARE_FIRMA for inactive companies...", file=sys.stderr)
    inactive_codes = get_inactive_inmatriculare_codes(args.stare)
    print(f"  -> {len(inactive_codes)} companies flagged inactive/closed", file=sys.stderr)

    print("Step 4/4: filtering OD_FIRME (legal form, date, tech, active)...", file=sys.stderr)
    kept = filter_firme(args.firme, tech_codes, inactive_codes,
                        from_date, to_date, args.out, code_to_category)
    print(f"  -> {kept} candidate companies written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
