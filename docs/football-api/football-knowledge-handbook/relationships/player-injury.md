# Player–Availability–Fixture Relationship

## Purpose
Model API-Football injury data at its actual fixture-observation grain.

## Overview
The relationship means “provider reported this player unavailable/questionable for this fixture,” not “player had a clinical injury spell.”

## Table of Contents
1. Meaning 2. Evidence 3. Model

## Semantics and Evidence
`/injuries` provides player, fixture, team, league-season, type, and reason. `/sidelined` is a separate period source.

## Cardinality, History, and Mapping
Many observations per player and fixture; preserve possible duplicates. Warehouse `availability_observation`; graph reified observation node. Spell inference requires explicit gap/reason policy and low confidence.
