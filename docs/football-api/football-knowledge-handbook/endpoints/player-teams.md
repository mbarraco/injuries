# Player Teams Knowledge Domain

## Purpose
Discover teams and seasons associated with a player’s career.

## Overview
`/players/teams` is career-scope discovery. It complements transfers and performance; it does not replace either.

## Table of Contents
Career scope, authority, mapping.

## Knowledge Produced
Player × team × season association; primary `PlayerTeamSeasonReference`.

## Relationships Created
`Player-[:OBSERVED_WITH_TEAM_IN_SEASON]->Team` qualified by season and source.

## Grain, Keys, and Time
One returned player-team-season association; `(player_id, team_id, season)` plus retrieval revision.

## Authority, Facts Missing, and Joins
Authoritative for returned association; missing transfer dates/types and match appearances. Join transfers for movement and fixture performances for playing evidence.

## Download, Freshness, Confidence, and Model
Targeted career enrichment; retain snapshots. ★★★★☆ association; ★★☆☆☆ implied membership interval.

## Inference, Redundancy, and Engineering Notes
Useful to schedule team/season calls. Do not deduplicate transfer events from it or overwrite player performance scopes.
