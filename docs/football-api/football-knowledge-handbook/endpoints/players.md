# Players Knowledge Domain

## Purpose

Represent player identity and scoped season statistics without confusing profiles, rosters, careers, and performances.

## Overview

`/players` produces player profile data together with statistics under a query scope. `/players/profiles` is a bulk profile-discovery producer; `/fixtures/players` is authoritative for player–fixture performance. A player’s reported position belongs to its source scope.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Acquisition and modeling

## Knowledge Produced

Identity/profile attributes such as name, birth data, nationality, height, and weight when returned; statistics such as appearances, lineups, minutes, rating, goals, and discipline under player/team/league/season scope.

## Primary and Secondary Entities

Primary: `Player`; secondary: `PlayerSeasonTeamStatistic`, `Team`, `LeagueSeason`, `Country`.

## Relationships Created

`Player-[:HAS_SEASON_STAT]->PlayerSeasonTeamStatistic`, then `PlayerSeasonTeamStatistic-[:FOR_TEAM]->Team` and `-[:IN_LEAGUE_SEASON]->LeagueSeason`.

## Grain, Keys, and Identifiers

Profile: one player identity. Statistics: one player × team × league × season record where returned. `player.id` is stable provider identity; do not derive a natural key from name/date of birth.

## Temporal Semantics and Authority

Profile is slowly changing and may be sparse. Statistics are season snapshots. Authoritative for returned scoped aggregates; not authoritative for individual match minutes, career totals across leagues, contract membership, or current roster.

## Facts Learned and Missing

Learns available profile and aggregates. It cannot answer every fixture performance or prove a player’s membership on an arbitrary date.

## Join Opportunities

Join fixture performance by player ID, transfers by player ID, squad membership by player/team scope, injuries by player/fixture, and trophies/sidelined by player reference. Aggregate both numerator and denominator before cross-scope rate joins.

## Download Strategy, Freshness, and History

Use pagination-aware league-season pulls for analytical breadth, profiles for bulk identity enumeration, and player filters for targeted repair. Refresh active season statistics periodically; preserve a snapshot history because ratings and totals evolve.

## Confidence

★★★★★ player ID; ★★★★☆ returned profile fields; ★★★★☆ returned scoped statistics; ★☆☆☆☆ career claims from one scope.

## Graph and Warehouse Mapping

`player`, `player_profile_version`, `player_season_team_stat_snapshot`. Graph uses a statistic node, not a direct timeless `PLAYED_FOR` edge.

## Inference, Redundancy, and Engineering Notes

Season minutes can support rates only after aggregating team rows within the intended league-season. `/fixtures/players` enriches to match grain; `/players/squads` describes a roster snapshot; `/players/teams` is career discovery. Index `(player_id, league_id, season, team_id)`.
