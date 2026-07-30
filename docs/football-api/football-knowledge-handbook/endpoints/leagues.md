# Leagues Knowledge Domain

## Purpose

Discover competitions, their seasons, and the vendor-advertised capability matrix that drives a crawl.

## Overview

`/leagues` is the catalogue authority for the API’s competition identity, country context, season list, and per-season feature coverage. It is the start of the ingestion plan, not a source of actual fixture or player records.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Acquisition and modeling

## Knowledge Produced

League identity and metadata; country context; type; season list; season coverage flags for fixtures, standings, players, injuries, odds, predictions, and match details where returned.

## Primary and Secondary Entities

Primary: `League`, `LeagueSeason`, `CoverageCapability`. Secondary: `Country`.

## Relationships Created

`League-[:IN_COUNTRY]->Country`, `League-[:HAS_SEASON]->LeagueSeason`, and `LeagueSeason-[:ADVERTISES_COVERAGE]->Feature`.

## Grain, Keys, and Identifiers

One league profile containing zero or more league-season capabilities. `league.id` is the stable provider identity; `LeagueSeason` is uniquely `(league_id, season)`.

## Temporal Semantics and Authority

League identity is slowly changing; season coverage is a mutable catalogue snapshot. Authoritative for advertised API capability, not for a guarantee that each response will contain records.

## Facts Learned and Missing

Learns competition metadata and candidate scope. Does not learn participating teams, fixtures, table values, or a complete historical archive.

## Join Opportunities

All competition-scoped endpoints join on `league.id` and `season`. Use fixtures for actual schedule, teams/standings for participation, and endpoint responses to validate capability claims.

## Download Strategy, Freshness, and History

Cold start: fetch globally and materialize a feature-qualified work list. Historical: iterate advertised league seasons, including `country: World` competitions selected by explicit policy. Incremental: refresh around season changes and periodically for coverage drift. Retain all snapshots.

## Confidence

★★★★★ league ID and returned season association; ★★★★☆ advertised feature availability; ★☆☆☆☆ completeness without response validation.

## Graph and Warehouse Mapping

Tables: `league`, `league_season`, `league_season_coverage_snapshot`. Graph: `(:League)-[:HAS_SEASON]->(:LeagueSeason)-[:COVERS {feature, observed_at}]->(:Feature)`.

## Inference, Redundancy, and Engineering Notes

Coverage flags create a crawl candidate set and can prioritize rich league-seasons. They cannot prove a fact existed. `/seasons` overlaps as a global season vocabulary; `/fixtures` is authoritative for actual fixture rows. Index `(league_id, season)` and version coverage instead of overwriting it.
