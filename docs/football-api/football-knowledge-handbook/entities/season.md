# League Season

## Purpose
Represent the competition-qualified season scope for facts and coverage.

## Overview
There is no safe universal season identity: use `(league_id, season)`.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Identity and Lifecycle
Suggested table/node: `league_season` / `(:LeagueSeason {league_id, season})`. Start/end dates and naming convention should not be invented if absent.

## Properties, Relationships, and Producers
`/leagues` creates the association/coverage; fixtures, standings, players, teams, and injuries populate scoped evidence.

## Historical Behavior, Confidence, and Inference
★★★★★ scope key; calendar/cross-year interpretation is competition-specific. Never join facts on season integer alone.
