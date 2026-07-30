# Fixtures Knowledge Domain

## Purpose

Provide the central match spine: fixture identity, scheduled time, status, competition, teams, result, and returned match context.

## Overview

`/fixtures` is the authoritative locator for fixture IDs and the backbone for all fixture-addressed enrichment. It may return embedded event, lineup, statistic, and player data for selected requests; model those at their native grains rather than storing them as a monolithic JSON-derived fixture table.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Acquisition and modeling

## Knowledge Produced

Fixture ID, schedule, status, referee, venue context, league-season, round, home and away participants, goals, score components, and possibly embedded detail collections.

## Primary and Secondary Entities

Primary: `Fixture`; secondary: `LeagueSeason`, `Round`, `Team`, `Venue`, `RefereeName`, and embedded match observations.

## Relationships Created

`Fixture-[:IN_LEAGUE_SEASON]->LeagueSeason`; home/away team edges; `Fixture-[:PLAYED_AT]->Venue`; `Fixture-[:IN_ROUND]->Round`.

## Grain, Keys, and Identifiers

One fixture response revision per `fixture.id`. Fixture ID is the stable join key for events, lineups, team statistics, player performances, injuries, predictions, and odds.

## Temporal Semantics and Authority

Scheduled/live/settled mutable record. Authoritative for returned fixture state and score at retrieval time; not an immutable final truth until reconciled after terminal status.

## Facts Learned and Missing

Learns match identity and state. Does not independently establish a full event timeline, all player minutes, clinical injuries, attendance, VAR rationale, or betting settlement.

## Join Opportunities

All fixture detail endpoints join by `fixture.id`. Leagues/teams supply catalogue detail; standings show a table snapshot; injuries add availability observations; head-to-head returns a filtered fixture set.

## Download Strategy, Freshness, and History

Cold start per selected league-season before detail endpoints. Historical backfill through league-season scopes; incremental rolling future/recent windows; live polling for active statuses; settlement reconciliation after final status. Cache successful empty results separately from access failures.

## Confidence

★★★★★ fixture ID and participants; ★★★★☆ state/score at retrieval; ★★★☆☆ finality before reconciliation.

## Graph and Warehouse Mapping

`fixture` with revision history, `fixture_team_role`, `fixture_venue`, and `round`. Graph centralizes `Fixture` with `HOME_TEAM`, `AWAY_TEAM`, `IN_LEAGUE_SEASON`, and detail edges.

## Inference, Redundancy, and Engineering Notes

Fixture time plus lineup/events can derive minutes only with documented rules and uncertainty. `/fixtures/rounds` partitions schedules; `/fixtures/headtohead` is a subset projection; separate detail endpoints are authoritative for their own grains. Index `(league_id, season, date)`, home/away IDs, and status.
