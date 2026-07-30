# Player

## Purpose
Represent a person who can appear in player profiles, squads, fixtures, transfers, availability, trophies, and sidelining records.

## Overview
Identity uses `player.id`. Profile properties are slowly changing; position, team, minutes, and selection belong to a stated scope.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Identity and Lifecycle
Stable identifier: provider `player.id`; natural names are display-only. Suggested table/node: `player` / `(:Player {source, api_id})`, with profile version history.

## Properties, Relationships, and Producers
Profile: `/players`, `/players/profiles`; season aggregate: `/players`; roster: `/players/squads`; match performance: `/fixtures/players`; selection: `/fixtures/lineups`; career: `/transfers`, `/trophies`, `/sidelined`; availability: `/injuries`.

## Historical Behavior, Confidence, and Inference
★★★★★ identity; ★★★★☆ returned profile; scoped facts require their team/league/season or fixture. Appearances prove playing evidence; transfers and squads support only labelled membership inferences.
