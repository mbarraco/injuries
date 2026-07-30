# Top Scorers Knowledge Domain

## Purpose
Publish a provider ranking for scoring within a league-season scope.

## Overview
`/players/topscorers` is a ranked aggregate projection, not a complete player population or career total.

## Table of Contents
Ranking, authority, mapping.

## Knowledge Produced
Ranked player season-stat records; primary `LeaderboardSnapshot`, secondary Player and LeagueSeason.

## Relationships, Grain, and Time
One player × leaderboard scope × retrieval snapshot. Key includes metric, league, season, rank, player, and observed time.

## Authority, Facts Missing, and Joins
Authoritative for returned ranking/scope; misses players outside cutoff and fixture events. Join `/players`/`fixtures/players` for underlying scope.

## Download, Freshness, Confidence, and Model
Refresh through season; ★★★★☆ returned rank. Store snapshot rows; never sum ranking records.

## Inference, Redundancy, and Engineering Notes
Can identify candidates for enrichment. It overlaps player season statistics but is not a substitute for paginated population ingestion.
