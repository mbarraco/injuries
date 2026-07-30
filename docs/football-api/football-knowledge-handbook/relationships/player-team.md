# Player–Team Relationship

## Purpose
Model the different meanings of a player’s connection to a team.

## Overview
There is no single timeless `PLAYED_FOR` fact. Keep transfer, roster snapshot, fixture selection, and fixture performance as distinct edges.

## Table of Contents
1. Meaning 2. Evidence 3. Model

## Semantics and Evidence
`TRANSFERRED_TO` comes from `/transfers`; `HAS_SQUAD_MEMBER` from `/players/squads`; `SELECTED_FOR` from lineups; `PERFORMED_FOR` from fixture players. Each is temporal and scoped.

## Cardinality, History, and Mapping
Player and Team are many-to-many over time. Use event/snapshot bridge tables; graph relationships carry fixture/date/source or use reified nodes. Inferred membership needs labelled boundaries and is never a replacement for direct performance.
