# Service Status Knowledge Domain

## Purpose

Expose account, subscription, and request-budget state required to plan acquisition safely.

## Overview

`/status` produces access metadata, not football-domain knowledge. It must never be modeled as a competition, player, or fixture source.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Subscription state and request allowance as reported at retrieval time.

## Primary and Secondary Entities

Primary: `ApiAccessSnapshot`. Secondary: account and subscription descriptors; these should be protected operational metadata.

## Relationships, Grain, and Keys

One row represents one status response. Key: `(provider, retrieved_at, payload_hash)`; no football foreign keys or stable football identifier.

## Temporal Semantics and Authority

Live snapshot. Authoritative only for the response’s account/quota view at that time; not authoritative for remaining availability after concurrent requests or any football fact.

## Facts Learned and Missing

Learns plan/account request state. Does not learn endpoint coverage, player data, or historical usage.

## Join, Download, Freshness, and History

Join to `ingest_run` operational records only. Query at run start and when diagnosing access; do not treat it as a durable daily budget guarantee.

## Confidence

★★★★★ for its own response snapshot; ★☆☆☆☆ for forecasting concurrent-run remaining quota.

## Graph and Warehouse Mapping

`(:IngestRun)-[:OBSERVED]->(:ApiAccessSnapshot)`. Store in `ops_api_status_snapshot`, access-controlled and retention-limited.

## Inference, Redundancy, and Engineering Notes

Can preflight a plan but cannot authorize a workload by itself. Response headers are complementary rate evidence; persist both. Never cache plan/auth/quota failures as football data.
