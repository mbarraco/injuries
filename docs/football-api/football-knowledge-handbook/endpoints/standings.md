# Standings Knowledge Domain

## Purpose

Represent a competition table as a scoped, mutable snapshot.

## Overview

`/standings` produces rank and aggregate records for teams in a league-season. A current/final response does not encode the table after every historical fixture unless those snapshots were collected.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Rank, points, played/win/draw/loss, goals, goal difference, form, description, group, and home/away aggregate splits where returned.

## Primary and Secondary Entities

Primary: `StandingSnapshot` and `StandingRow`; secondary: `LeagueSeason`, `Team`, `StandingGroup`.

## Relationships, Grain, and Keys

One row per team × table/group × league-season × retrieval snapshot. Key includes snapshot time or payload revision; rank alone is never a key.

## Temporal Semantics and Authority

Snapshot, changing through season. Authoritative for the returned table state, not for points evolution between retained snapshots or disciplinary decisions absent from response.

## Facts Learned and Missing

Learns provider table aggregates. Does not prove event-level causes, all tie-break computations, or historical table state not captured.

## Join, Download, Freshness, and History

Fetch for each selected league-season; refresh after fixture windows and at final settlement. Join team/league season. Reconstruct a time series only from retained snapshots or explicit re-calculation rules plus complete fixtures.

## Confidence

★★★★★ returned row at retrieval; ★★★☆☆ recomputed history; ★☆☆☆☆ unobserved daily table state.

## Graph and Warehouse Mapping

`standing_snapshot`, `standing_row`; graph `StandingSnapshot-[:HAS_ROW]->Team` with rank/points properties.

## Inference, Redundancy, and Engineering Notes

Fixtures provide results; standings provide the vendor table. Use each for its own authority and flag discrepancies. Partition by league season and index `(league_id, season, retrieved_at, team_id)`.
