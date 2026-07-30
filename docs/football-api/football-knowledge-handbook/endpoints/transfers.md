# Transfers Knowledge Domain

## Purpose

Record player movement between teams as career events.

## Overview

`/transfers` is the primary producer for returned player movement. Transfers are not match participation, squad registration, contracts, salaries, or proof that a player actually appeared for either club.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Player identity, source team, destination team, transfer date, and returned transfer type.

## Primary and Secondary Entities

Primary: `Transfer`; secondary: `Player`, `Team`, `Career`.

## Relationships, Grain, and Keys

One player movement event. No documented transfer ID: create a collision-aware natural event key from player, date, source, destination, type, and source payload hash.

## Temporal Semantics and Authority

Historical event that may be corrected. Authoritative for returned movement details; not authoritative for contract start/end, registration, fee, loan terms, or appearances.

## Facts Learned and Missing

Learns a reported move and its parties/date/type. Does not learn salaries, medicals, exact effective time, or which competition the player played in.

## Join Opportunities

Join players/teams by ID, fixture performances to evidence appearances, squads for observed roster membership, injuries/sidelined around a move, and trophies for career context.

## Download Strategy, Freshness, and History

Fetch full history per discovered player where plan permits; refresh active players frequently during windows and periodically otherwise. Keep tombstone/seen tracking because returned histories can change.

## Confidence

★★★★★ returned parties/date; ★★★★☆ type; ★★☆☆☆ implied continuous membership between transfers.

## Graph and Warehouse Mapping

`transfer` fact with `from_team_id`, `to_team_id`, date, type, source hash. Graph reifies `(:Transfer)-[:OF_PLAYER]->(:Player)`, `-[:FROM]->(:Team)`, `-[:TO]->(:Team)`.

## Inference, Redundancy, and Engineering Notes

Ordered transfers can propose a career timeline; gaps, loans, youth teams, and registration exceptions make membership an inference. `/players/teams` supports discovery; fixtures are the authority for playing evidence. Index player/date and source/destination/date.
