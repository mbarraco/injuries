#!/usr/bin/env python3
"""Diagnostic: why did 173/173 individual team fetches resolve nothing?
Checks the actual status codes and response bodies logged for /teams/{id}
calls in the most recent resolve log, to tell apart genuine 404s from
Sportmonks' silent 200+empty out-of-plan gating (already proven to exist
for leagues earlier in this project)."""
import glob
import json
import os

BASE = os.path.dirname(__file__)
logs = sorted(glob.glob(os.path.join(BASE, "logs", "sportmonks-resolve.*.log")))
latest = logs[-1]
print(f"reading {latest}")

statuses = {}
samples = []
with open(latest, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if "/teams/" in rec["url"] and "/multi/" not in rec["url"] and "search" not in rec["url"]:
            st = rec["status"]
            statuses[st] = statuses.get(st, 0) + 1
            if len(samples) < 5:
                samples.append(rec)

print("status code breakdown for /teams/{id} calls:", statuses)
print("\nsample responses:")
for s in samples:
    body = s["body"]
    data = body.get("data") if isinstance(body, dict) else None
    print(f"  {s['url']} -> HTTP {s['status']}, data={data!r}")
