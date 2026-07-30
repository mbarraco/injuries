# Top Assists Knowledge Domain

## Purpose
Publish a provider ranking for assists within a league-season scope.

## Overview
`/players/topassists` follows the same leaderboard semantics as top scorers, with assists as the ranked measure.

## Table of Contents
Ranking, authority, mapping.

## Knowledge Produced
Ranked player season-stat records at player × league-season × snapshot grain.

## Authority, Missing Facts, and Joins
Authoritative for returned rank/assist aggregate, not complete player coverage or event-level assist semantics. Join player statistics and fixture events/performance for enrichment.

## Download, Freshness, Confidence, and Model
Refresh during active season; ★★★★☆ returned rank. Store `leaderboard_snapshot(metric='assists')` with scope and time.

## Inference, Redundancy, and Engineering Notes
Ranking shifts are snapshot changes. Do not infer career-assist leader or complete league population from a leaderboard cutoff.
