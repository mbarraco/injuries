"""Generic raw-JSON cache, shared by every vendor.

Every fetched response is persisted here before any processing, so nothing
downloaded is ever lost or re-fetched. This is what lets a dataset outlive the
subscription that produced it: once a response is on disk it is the durable
record, and the derived databases are rebuildable artifacts.

Moved out of `sportmonks_client` unchanged — it never had anything
vendor-specific in it.
"""
from __future__ import annotations

import json
import os


def read_cache(path):
    """Return the cached object at `path`, or None if it isn't cached yet."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_cache(path, obj):
    """Persist `obj` as JSON, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False)
