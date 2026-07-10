"""
geocode_candidates.py  (v4 - Bucharest sector centroid fallback)

Key improvement: when street-level geocoding fails for a Bucharest address,
falls back to a hardcoded sector centroid rather than letting Nominatim
guess and land in the wrong sector.

USAGE:
  python geocode_candidates.py \
      --candidates candidates_enriched.csv \
      --out candidates_geocoded.csv \
      [--cache geocode_cache.json] \
      [--retry-failed]
"""

import argparse
import json
import os
import re
import sys
import time
import pandas as pd
import requests

DELIM = "^"
NOMINATIM_USER_AGENT = "romania-startup-map/4.0 (dana.juncu@diconium.com)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RATE_LIMIT = 1.1

# Bucharest sector centroids (approximate geographic centers)
BUCHAREST_SECTORS = {
    "1": (44.4669, 26.0820),
    "2": (44.4453, 26.1200),
    "3": (44.4185, 26.1200),
    "4": (44.3950, 26.0950),
    "5": (44.4050, 26.0500),
    "6": (44.4300, 26.0250),
}

RANK_ABBREVS = re.compile(
    r'^(SLT\.|LT\.|CPT\.|MR\.|LTC\.|COL\.|GL\.|GEN\.|ADM\.|DR\.|ING\.|'
    r'PROF\.|AV\.|CDOR\.|VCEAMD\.|AMR\.|LT\.CDR\.|SG\.MAJ\.|PLT\.ADJ\.)\s*',
    re.IGNORECASE
)


def nominatim_query(query: str, session: requests.Session) -> tuple:
    try:
        resp = session.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "ro"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"  Warning: '{query}': {e}", file=sys.stderr)
    return None, None


def clean_locality(val):
    if not val or not isinstance(val, str):
        return ""
    val = val.strip()
    for prefix in ["Municipiul ", "Orașul ", "Comuna ", "Sat ", "Sectorul ",
                   "municipiul ", "orașul ", "comuna ", "sat ", "sectorul "]:
        if val.startswith(prefix):
            val = val[len(prefix):]
    return val.strip()


def clean_street(val):
    if not val or not isinstance(val, str):
        return ""
    val = RANK_ABBREVS.sub("", val.strip()).strip()
    return val


def clean_number(val):
    if not val or not isinstance(val, str):
        return ""
    return val.strip().split("-")[0].split("/")[0].strip()


def is_bucharest(judet: str) -> bool:
    return "BUCURE" in judet.upper()


def build_address_key(row: pd.Series) -> tuple:
    strada = clean_street(str(row.get("ADR_DEN_STRADA", "") or ""))
    nr = clean_number(str(row.get("ADR_NR_STRADA", "") or ""))
    localitate = clean_locality(str(row.get("ADR_LOCALITATE", "") or ""))
    judet = clean_locality(str(row.get("ADR_JUDET", "") or ""))
    sector = str(row.get("ADR_SECTOR", "") or "").strip()
    postal = str(row.get("ADR_COD_POSTAL", "") or "").strip()
    return (strada, nr, localitate, judet, sector, postal)


def geocode_address(key: tuple, session: requests.Session) -> tuple:
    strada, nr, localitate, judet, sector, postal = key
    bucharest = is_bucharest(judet)

    # --- Build Nominatim queries ---
    queries = []

    if strada:
        # Critical: street and number joined with space, no comma between them.
        # Nominatim needs "NERVA TRAIAN 27, Sector 3, Bucuresti"
        # not "NERVA TRAIAN, 27, Sector 3, Bucuresti".
        # Also use "Bucuresti" without diacritics - more reliably matched.
        street_part = f"{strada} {nr}".strip() if nr else strada
        if bucharest and sector:
            queries.append(
                (f"{street_part}, Sector {sector}, Bucuresti, Romania", "street"))
        if localitate:
            queries.append(
                (f"{street_part}, {localitate}, Romania", "street"))
        # Try without number if number-specific query fails
        if nr:
            if bucharest and sector:
                queries.append(
                    (f"{strada}, Sector {sector}, Bucuresti, Romania", "street"))
            if localitate:
                queries.append(
                    (f"{strada}, {localitate}, Romania", "street"))

    if postal:
        queries.append((f"{postal}, Romania", "postal"))

    # For non-Bucharest, fall back to locality
    if not bucharest:
        if localitate and judet:
            queries.append((f"{localitate}, {judet}, Romania", "locality"))
        elif localitate:
            queries.append((f"{localitate}, Romania", "locality"))
        if judet:
            queries.append((f"{judet}, Romania", "county"))

    # Try Nominatim queries
    for query, precision in queries:
        lat, lon = nominatim_query(query, session)
        time.sleep(RATE_LIMIT)
        if lat is not None:
            return lat, lon, precision

    # --- Bucharest fallback: use sector centroid ---
    if bucharest and sector and sector in BUCHAREST_SECTORS:
        lat, lon = BUCHAREST_SECTORS[sector]
        return lat, lon, "sector_centroid"

    # Last resort: Bucharest city center
    if bucharest:
        return 44.4268, 26.1025, "city_center"

    return None, None, "failed"


def load_cache(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="geocode_cache.json")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Re-attempt addresses previously marked failed or "
                         "sector_centroid/city_center (to try improved queries)")
    args = ap.parse_args()

    print("Loading candidates...", file=sys.stderr)
    df = pd.read_csv(args.candidates, sep=DELIM, dtype=str,
                     encoding="utf-8", keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    print(f"  -> {len(df):,} rows", file=sys.stderr)

    df["_addr_key"] = df.apply(
        lambda r: json.dumps(build_address_key(r), ensure_ascii=False), axis=1)
    unique_keys = df["_addr_key"].unique()
    print(f"  -> {len(unique_keys):,} unique addresses", file=sys.stderr)

    cache = load_cache(args.cache)

    if args.retry_failed:
        retry_precisions = {"failed", "sector_centroid", "city_center"}
        retry_keys = [k for k, v in cache.items()
                      if v.get("precision") in retry_precisions]
        for k in retry_keys:
            del cache[k]
        print(f"  -> retrying {len(retry_keys):,} previously unresolved addresses",
              file=sys.stderr)

    already_done = sum(1 for k in unique_keys if k in cache)
    remaining = len(unique_keys) - already_done
    print(f"  -> {already_done:,} cached, {remaining:,} to fetch", file=sys.stderr)
    if remaining > 0:
        print(f"  -> Estimated time: {remaining * RATE_LIMIT / 60:.0f} minutes",
              file=sys.stderr)

    session = requests.Session()
    session.headers.update({"User-Agent": NOMINATIM_USER_AGENT})

    done = 0
    precision_counts = {}

    for key_str in unique_keys:
        if key_str in cache:
            p = cache[key_str].get("precision", "locality")
            precision_counts[p] = precision_counts.get(p, 0) + 1
            continue

        key = tuple(json.loads(key_str))
        lat, lon, precision = geocode_address(key, session)
        cache[key_str] = {"lat": lat, "lon": lon, "precision": precision}
        precision_counts[precision] = precision_counts.get(precision, 0) + 1
        done += 1

        if done % 100 == 0:
            save_cache(args.cache, cache)
            pct = (already_done + done) / len(unique_keys) * 100
            print(f"  [{already_done + done:,}/{len(unique_keys):,} | {pct:.1f}%] "
                  f"{key[2]}, {key[3]} -> {precision}", file=sys.stderr)

    save_cache(args.cache, cache)

    print(f"\nGeocoding precision breakdown:", file=sys.stderr)
    for level, count in sorted(precision_counts.items(),
                                key=lambda x: -x[1]):
        print(f"  {level}: {count:,}", file=sys.stderr)

    df["LAT"] = df["_addr_key"].map(lambda k: cache.get(k, {}).get("lat"))
    df["LON"] = df["_addr_key"].map(lambda k: cache.get(k, {}).get("lon"))
    df["GEO_PRECISION"] = df["_addr_key"].map(
        lambda k: cache.get(k, {}).get("precision", "failed"))
    df = df.drop(columns=["_addr_key"])

    resolved = df["LAT"].notna().sum()
    print(f"\n  -> {resolved:,} rows with coordinates", file=sys.stderr)
    print(f"  -> {len(df) - resolved:,} failed", file=sys.stderr)
    df.to_csv(args.out, sep=DELIM, index=False, encoding="utf-8")
    print(f"  -> written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
