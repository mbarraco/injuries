# Fixture–Player Relationship

## Purpose
Separate selection and performance edges between a player and a fixture.

## Overview
Lineups answer selection; `/fixtures/players` answers returned performance. Both are team-qualified and revisionable.

## Table of Contents
1. Meaning 2. Evidence 3. Model

## Semantics and Evidence
`SELECTED_FOR` uses `/fixtures/lineups`; `PERFORMED_IN` uses `/fixtures/players`; goals/cards/substitutions add event context.

## Cardinality, History, and Mapping
Many players per fixture and many fixtures per player. Keep `lineup_member` and `player_fixture_performance` separate facts. An absent performance row is not universally proof of non-participation.
