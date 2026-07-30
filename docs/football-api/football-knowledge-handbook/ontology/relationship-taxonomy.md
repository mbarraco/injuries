# Relationship Taxonomy

## Purpose

Define edges that can be asserted from API-Football evidence.

## Overview

Every edge is qualified by source endpoint, query scope, and observation time where the provider can revise it.

## Table of Contents

1. Structural edges
2. Temporal edges
3. Match edges

| Predicate | From → To | Temporal qualification | Evidence |
|---|---|---|---|
| `IN_COUNTRY` | League/Team → Country | slowly changing | leagues, teams |
| `HAS_SEASON` | League → LeagueSeason | season | leagues, seasons |
| `PARTICIPATES_IN` | Team → LeagueSeason | season | teams, fixtures, standings |
| `HOSTS` / `VISITS` | Team → Fixture | fixture | fixtures |
| `SELECTED_FOR` | Player → Fixture | fixture | fixtures/lineups |
| `PERFORMED_IN` | Player → Fixture | fixture | fixtures/players |
| `TRANSFERRED_TO` | Player → Team | transfer date | transfers |
| `WAS_UNAVAILABLE_FOR` | Player → Fixture | fixture | injuries |
| `WON` | Player/Coach → Trophy | award date/season | trophies |
| `QUOTED_FOR` | Bookmaker → Fixture market | retrieval time | odds |
