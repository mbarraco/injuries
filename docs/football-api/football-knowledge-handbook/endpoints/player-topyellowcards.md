# Top Yellow Cards Knowledge Domain

## Purpose
Publish a provider ranking for yellow-card totals within a league season.

## Overview
`/players/topyellowcards` is a scoped ranking projection, not an event ledger.

## Table of Contents
Ranking, authority, mapping.

## Knowledge Produced
Player × league-season × yellow-card rank snapshot.

## Authority, Missing Facts, and Joins
Authoritative for returned aggregate/rank; missing every event context and players outside result cutoff. Join player statistics and fixture events.

## Download, Freshness, Confidence, and Model
Refresh during season; ★★★★☆ returned ranking. Store metric-scoped leaderboard snapshot.

## Inference, Redundancy, and Engineering Notes
Do not derive suspension status from yellow-card totals without competition rules and current disciplinary state.
