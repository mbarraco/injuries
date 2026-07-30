# Fixture Player Statistics Knowledge Domain

## Purpose

Measure each returned player’s performance in a specific fixture.

## Overview

`/fixtures/players` is the authoritative player-match performance producer. It is the preferred direct evidence for minutes, ratings, and detailed player metrics at fixture grain.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Player identity; team; appearances, starts, minutes, position, rating; goals/assists; shots, passes, tackles, duels, dribbles, fouls, cards, penalties, and goalkeeper measurements where returned.

## Primary and Secondary Entities

Primary: `PlayerFixturePerformance`; secondary: `Fixture`, `Player`, `Team`, `PerformanceMetric`.

## Relationships, Grain, and Keys

One player × fixture × team performance, with metric values under a response revision. Key `(fixture_id, player_id, team_id)` plus revision; keep absent/null metric values distinct from zero.

## Temporal Semantics and Authority

Live/settled revisionable. Authoritative for returned match-level metrics, including reported minutes; not authoritative for full tracking data, physical load, or career totals.

## Facts Learned and Missing

Learns direct performance and minutes at match grain. Does not establish contract membership, medical state, or a team-season total without aggregation.

## Join, Download, Freshness, and History

Highest-value fixture detail crawl after fixture spine. Poll/reconcile completed fixtures, then aggregate explicitly for season facts. Join to lineups/events for consistency and explanatory context.

## Confidence

★★★★★ player-fixture identity; ★★★★☆ returned minutes/metrics after settlement; ★★☆☆☆ unobserved player did not play.

## Graph and Warehouse Mapping

Long metric fact or wide performance table with provenance; graph reifies `PlayerFixturePerformance` between player, fixture, and team.

## Inference, Redundancy, and Engineering Notes

Summing minutes derives competition-scoped minutes only after deduplicating fixture revisions and respecting team/league scope. `/players` season statistics overlaps as an aggregate and is a useful reconciliation source, not an interchangeable row source.
