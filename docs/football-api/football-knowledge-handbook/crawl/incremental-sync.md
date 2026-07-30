# Incremental Sync

## Purpose

Keep an existing corpus current while minimizing quota use and preserving revisions.

## Overview

Drive incremental work by time and state, not full historical re-downloads. Separate low-churn catalogue refreshes, upcoming/live fixture polling, and recently-settled reconciliation.

## Table of Contents

1. Watermarks
2. Schedules
3. Idempotency

| Class | Work selection | Write policy |
|---|---|---|
| Catalogue | season boundary and periodic refresh | version changed attributes |
| Upcoming fixtures | rolling future window | upsert new schedules |
| Live/recent fixtures | status-based active set | append revision when payload changes |
| Injuries | documented date query for elapsed dates | deduplicate only at source-record level |
| Transfers/trophies/sidelined | active people plus periodic reconciliation | upsert and retain seen timestamps |
| Odds/predictions | fixture start horizon | append snapshots, never overwrite quotes |

## Watermarks

Store `last_successful_at` per endpoint and *scope*, not globally. A failure in one league-season must not advance its watermark. Use a lookback window for mutable fixtures and provider snapshots; a strict “greater than last timestamp” filter misses corrections and delayed publications.

## Idempotency

Raw cache writes are idempotent by canonical request key plus payload hash. Normalized upserts use stable vendor IDs, while snapshot tables use `(scope, retrieved_at, payload_hash)`. Retry only transient network/server/minute-limit failures with bounded backoff; stop cleanly on daily exhaustion.
