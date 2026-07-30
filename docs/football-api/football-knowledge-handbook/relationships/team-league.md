# Team–League Relationship

## Purpose
Model competition participation as a league-season-scoped relation.

## Overview
Teams, standings, and fixtures each evidence participation differently; none should be reduced to an unqualified timeless edge.

## Table of Contents
1. Meaning 2. Evidence 3. Model

## Semantics and Evidence
`/teams?league&season` and `/standings` provide scoped participation snapshots; `/fixtures` proves a specific fixture in a league season.

## Cardinality, History, and Mapping
Many-to-many by `LeagueSeason`. Warehouse bridge `team_league_season(team_id, league_id, season, source)`; graph `Team-[:PARTICIPATES_IN]->LeagueSeason`. Preserve source and time.
