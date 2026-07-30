"""Field inventory of every cached API-Football payload — the input to schema design.

Read-only and offline. Answers the question a schema cannot be designed without:
**which fields does each endpoint actually populate, and how often?**

A field that exists in one sample but is null in 90% of rows is not a column you
build a page on. So this reports fill rates, not just presence — the difference
between "the vendor has date of birth" and "the vendor has date of birth for
enough players to analyse age".

Specifically checks whether the dimensions the existing Sportmonks-backed app
depends on (`app/schema.sql`) can be reproduced here:
  - player: position, date_of_birth, nationality, height, weight
  - team:   country, founded
  - the minutes-played denominator that turns counts into rates

Usage:
    uv run python scripts/apifootball/af_inspect_payloads.py
    uv run python scripts/apifootball/af_inspect_payloads.py --sample 500
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(BASE, "data", "raw", "apifootball")

# (label, directory, key holding the record list, path to the sub-object we
# care about). A None path means the record itself is the object of interest.
SOURCES = [
    ("players",    os.path.join(RAW, "players"),    "players",   None),
    ("teams",      os.path.join(RAW, "teams"),      "teams",     None),
    ("fixtures",   os.path.join(RAW, "fixtures"),   "fixtures",  None),
    ("standings",  os.path.join(RAW, "standings"),  "standings", None),
    ("injuries",   os.path.join(RAW, "injuries"),   "injuries",  None),
]

# Fields the existing app's schema needs, so their absence is called out loudly
# rather than left for someone to discover mid-build.
CRITICAL = {
    "players": ["id", "name", "firstname", "lastname", "age", "birth",
                "nationality", "height", "weight", "position", "photo"],
    "teams": ["id", "name", "country", "founded", "code"],
}


def walk(obj, prefix="", out=None, depth=0, max_depth=5):
    """Flatten a nested dict into dotted paths -> whether the leaf is populated.

    Lists are summarised by their first element: the goal is a field inventory,
    not an exhaustive traversal, and every element of an API response array is
    the same shape in practice.
    """
    out = {} if out is None else out
    if depth > max_depth:
        return out
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                walk(value, path, out, depth + 1, max_depth)
            else:
                out[path] = value is not None and value != ""
    elif isinstance(obj, list) and obj:
        walk(obj[0], f"{prefix}[]", out, depth + 1, max_depth)
    return out


def inspect(label, directory, key, sample_limit):
    files = sorted(glob.glob(os.path.join(directory, "*.json")))
    if not files:
        print(f"\n### {label}\n  (nothing cached at {directory})")
        return None

    present = Counter()
    total = 0
    for path in files:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        for record in (document.get(key) or []):
            total += 1
            for field, populated in walk(record).items():
                if populated:
                    present[field] += 1
            if total >= sample_limit:
                break
        if total >= sample_limit:
            break

    print(f"\n### {label} — {total:,} records sampled from {len(files)} file(s)\n")
    if not total:
        print("  (files present but no records inside)")
        return None
    width = max(len(f) for f in present) if present else 20
    for field, count in sorted(present.items(), key=lambda kv: -kv[1]):
        share = count / total
        flag = "" if share > 0.9 else ("  <- sparse" if share > 0.1 else "  <- MOSTLY NULL")
        print(f"  {field.ljust(width)}  {share:6.1%}{flag}")
    return present, total


def main(argv=None):
    parser = argparse.ArgumentParser(description="Field inventory of cached API-Football payloads")
    parser.add_argument("--sample", type=int, default=2000,
                        help="records to sample per source (default 2000)")
    args = parser.parse_args(argv)

    results = {}
    for label, directory, key, _sub in SOURCES:
        outcome = inspect(label, directory, key, args.sample)
        if outcome:
            results[label] = outcome

    # ---- the verdict the schema decision actually rests on ---------------- #
    print("\n\n### Can we reproduce the existing app's dimensions?\n")
    for label, wanted in CRITICAL.items():
        if label not in results:
            print(f"  {label}: NOT CACHED — cannot tell")
            continue
        present, total = results[label]
        print(f"  {label}:")
        for field in wanted:
            # A field may appear at any nesting depth; match on the leaf name.
            # Match the leaf OR any path segment: `birth` lives as
            # `player.birth.date`, so a leaf-only match reported it ABSENT
            # when it is in fact 100% populated. A check that cannot return a
            # positive is worse than no check.
            hits = [(path, count) for path, count in present.items()
                    if field in [seg.rstrip("[]") for seg in path.split(".")]]
            if not hits:
                print(f"    {field:14} ABSENT")
            else:
                path, count = max(hits, key=lambda kv: kv[1])
                print(f"    {field:14} {count / total:6.1%}  ({path})")

    # Minutes played is the rate denominator and lives only in per-fixture
    # data, which is a separate 32,000-call crawl.
    fp_dir = os.path.join(RAW, "fixture_players")
    cached = len(glob.glob(os.path.join(fp_dir, "*", "*.json")))
    print(f"\n  minutes denominator (fixture_players): {cached:,} fixtures cached")
    if not cached:
        print("    -> NOT yet fetched. Injury RATES are impossible until this "
              "crawl runs;\n       only absence COUNTS can be built today.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
