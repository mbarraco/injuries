# Team Seasons Knowledge Domain

## Purpose
Discover seasons associated with a returned team.

## Overview
`/teams/seasons` is a historical discovery aid, not a complete record of every league, fixture, or roster.

## Table of Contents
Discovery, authority, mapping.

## Knowledge Produced
Team-season associations; primary entity `TeamSeasonReference`, secondary `Team` and `SeasonReference`.

## Relationships Created
`Team-[:OBSERVED_IN_SEASON]->SeasonReference`.

## Grain, Keys, and Time
One team × season row; key `(team_id, season)`; historical reference snapshot.

## Authority, Facts Missing, and Joins
Authoritative for returned association; not for league participation or performance. Join `/leagues`, fixtures, standings, and players to add competition scope.

## Download, Freshness, Confidence, and Model
Fetch by team after discovery and refresh periodically. ★★★★☆ returned association. Store `team_season_reference`; graph edge is source-qualified.

## Inference, Redundancy, and Engineering Notes
Narrows historical queries but cannot prove continuous membership. It overlaps team/fixture/standing discovery; index `(team_id, season, observed_at)`.
