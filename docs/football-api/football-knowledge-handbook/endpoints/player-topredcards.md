# Top Red Cards Knowledge Domain

## Purpose
Publish a provider ranking for red-card totals within a league season.

## Overview
`/players/topredcards` is a scoped ranking projection, not a sanction or event-history authority.

## Table of Contents
Ranking, authority, mapping.

## Knowledge Produced
Player × league-season × red-card rank snapshot.

## Authority, Missing Facts, and Joins
Authoritative for returned aggregate/rank; missing disciplinary outcome and detailed incident context. Join fixture player statistics/events.

## Download, Freshness, Confidence, and Model
Refresh during season; ★★★★☆ returned ranking. Store metric-scoped leaderboard snapshot.

## Inference, Redundancy, and Engineering Notes
Never infer a current ban merely from rank or card count; rules and appeals are outside this endpoint.
