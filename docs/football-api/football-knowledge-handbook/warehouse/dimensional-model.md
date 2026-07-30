# Dimensional Model

## Purpose

Describe analytics-friendly facts without sacrificing source grain.

## Overview

Facts must not cross incompatible grains. A fixture-level event, a player–fixture performance, and a team–league–season aggregate are separate facts.

## Table of Contents

1. Facts
2. Dimensions
3. Conformed joins

| Fact | Grain | Additivity |
|---|---|---|
| `fact_fixture` | one fixture revision | score values additive only with outcome rules |
| `fact_fixture_event` | one event observation | countable after deduplication policy |
| `fact_player_fixture_performance` | player × fixture × team | minutes additive by player/date only |
| `fact_availability` | player × fixture observation | never call it injury count |
| `fact_transfer` | player movement event | countable by defined natural-event key |
| `snapshot_standing` | team × league season × retrieval | non-additive snapshot |
| `snapshot_odds` | bookmaker × bet × value × fixture × retrieval | non-additive quote |

## Conformed Dimensions

`dim_player`, `dim_team`, `dim_league`, `dim_league_season`, `dim_venue`, `dim_date`, and `dim_source` should be shared across facts. Retain source IDs in every fact to enable replay and reconciliation.

## Guardrails

Aggregate each side before joining availability to minutes. A player may have multiple team/league rows in a season; a direct many-to-many join can multiply absence counts while leaving the minutes denominator unchanged.
