# Player Seasons Knowledge Domain

## Purpose
Discover seasons associated with a player.

## Overview
`/players/seasons` constrains player-history query planning; it is not a player performance, team, or league membership authority.

## Table of Contents
Discovery, authority, mapping.

## Knowledge Produced
Player-season references; primary `PlayerSeasonReference`, secondary `Player`.

## Relationships Created
`Player-[:OBSERVED_IN_SEASON]->SeasonReference`.

## Grain, Keys, and Time
One player × season reference, key `(player_id, season)`; historical snapshot.

## Authority, Facts Missing, and Joins
Authoritative for returned association only. Missing team, league, minutes, and appearances; join `/players`, `/players/teams`, and fixture performances.

## Download, Freshness, Confidence, and Model
Fetch targeted players during historical enrichment; ★★★★☆ returned association. Store source scope/time.

## Inference, Redundancy, and Engineering Notes
Can reduce exploratory calls but does not prove continuous football activity. Do not join on season alone.
