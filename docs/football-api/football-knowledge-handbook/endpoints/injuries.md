# Availability and Injuries Knowledge Domain

## Purpose

Record API-Football’s fixture-scoped reports that a player may be unavailable for a match.

## Overview

`/injuries` is the authority for its returned availability records, but its grain is a player–fixture observation. It does **not** supply an injury-spell identifier, start/end date, recovery date, medical severity, or clinical diagnosis. Its free-text reason can include non-injury causes; the returned type must be preserved.

## Table of Contents

1. Knowledge and grain
2. Authority and temporal semantics
3. Inference boundaries

## Knowledge Produced

Player, team, fixture, league-season, availability type, and free-text reason for a returned record.

## Primary and Secondary Entities

Primary: `AvailabilityObservation`; secondary: `Player`, `Team`, `Fixture`, `LeagueSeason`, `ReasonClassification`.

## Relationships Created

`Player-[:HAS_AVAILABILITY]->AvailabilityObservation-[:FOR_FIXTURE]->Fixture`; the observation is associated with team and league season.

## Grain, Keys, and Identifiers

One returned player–fixture record. There is no documented spell ID. Use a surrogate source-row key and preserve duplicates; do not force a player-fixture unique constraint because multiple provider records can be meaningful.

## Temporal Semantics and Authority

Historical fixture-scoped observation, mutable if vendor revisions occur. Authoritative for the label on the returned fixture; not authoritative for a continuous absence interval or medical fact.

## Facts Learned and Missing

Learns that the provider reported a player as `Missing Fixture` or potentially `Questionable` with a reason for a fixture. Missing: onset, recovery, games missed as a spell, severity, diagnosis, treatment, and certainty that a doubtful player did not participate.

## Join Opportunities

Join fixture ID to date/status/opponents, player ID to profiles and minutes, team ID to participation, and transfers by date for context. Join reason mappings without overwriting the raw string. Never sum confirmed and questionable values as one absence metric.

## Download Strategy, Freshness, and History

Historical backfill by eligible league-season; incremental sync by documented date query; target player/team/fixture queries for repair. Fetch fixture spine independently and validate every referenced fixture. Re-run coverage discovery periodically because coverage changes.

## Confidence

★★★★★ player-fixture availability record; ★★★★☆ confirmed-missing label; ★★☆☆☆ normalized injury category; ★☆☆☆☆ inferred spell boundaries.

## Graph and Warehouse Mapping

`availability_observation(player_id, fixture_id, team_id, league_id, season, type, raw_reason, retrieved_at)`. Graph uses a reified observation, never direct timeless `Player-[:INJURED]->Team`.

## Inference, Redundancy, and Engineering Notes

Consecutive fixtures with the same player/reason can form a **labelled heuristic** spell, only after defining permitted fixture gaps and team changes. Fixture player statistics can falsify “did not play” for an observed questionable record. `/sidelined` is interval-like career history but is not an interchangeable source. Index player, fixture, team, league-season, type, raw reason, and fixture date.
