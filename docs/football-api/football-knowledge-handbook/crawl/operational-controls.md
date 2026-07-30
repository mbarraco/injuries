# Crawl Operational Controls

## Purpose

Define quota-aware, failure-safe controls shared by every acquisition workflow.

## Overview

The crawler is a durable state machine, not a loop over URLs. It should make the next eligible unit of work explicit and leave a replayable audit trail after every request.

## Table of Contents

1. Rate limits
2. Retry policy
3. Checkpointing

## Rate Limits

Read provider response headers and service responses as observations, not compile-time constants. Pace a single shared client beneath the per-minute ceiling; budget batch work beneath the daily ceiling. The project has observed that API-Football can report access/rate conditions in the response body even with HTTP success, so classify body errors before treating a response as data.

## Retry Policy

Retry bounded transient network/server/minute-limit conditions with jittered backoff. Stop and checkpoint for daily exhaustion. Do not cache auth, plan, quota, or malformed-response failures as successful empty results. Retain the vendor error text in the run log.

## Checkpointing and Recovery

Define work keys by producer grain: `(league, season)` for scoped endpoints and `(fixture, detail_endpoint)` for detail enrichments. Recompute missing work from durable raw cache after restart. A checkpoint advances only after raw payload validation and atomic write complete.

## Parallelization

Parallelize independent work keys only behind one thread-safe pacing and quota view. Avoid duplicate processes that each assume they own the full per-minute allowance. Concurrency improves latency; it never raises plan quota.
