# Team Season Statistics Knowledge Domain

## Purpose

Provide provider-computed aggregate statistics for a team in a competition season.

## Overview

`/teams/statistics` is a scope-sensitive snapshot. A date parameter can change the as-of point; without it, the response summarizes the provider’s current view of games in the scope.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Results, goals, home/away splits, form, wins/losses, clean sheets, failed scoring, cards by minute, used lineups, and other returned season aggregates.

## Primary and Secondary Entities

Primary: `TeamSeasonStatisticSnapshot`; secondary: `Team`, `LeagueSeason`, optional `AsOfDate`, statistic dimensions.

## Relationships, Grain, and Keys

One snapshot per team × league × season × optional as-of date × retrieval time. Team and league/season are foreign keys; the parameter scope is part of identity.

## Temporal Semantics and Authority

Mutable aggregate snapshot. Authoritative for its returned scope and retrieval; not for fixture-level source facts, historical daily values not requested, or all-competition totals.

## Facts Learned and Missing

Learns provider aggregates. Does not give a normalized match fact table, player contribution, or an auditable derivation of every aggregate.

## Join, Download, Freshness, and History

Fetch after teams and fixtures; schedule active teams more frequently than inactive ones. Join team and league season, retain as-of/query metadata. Use fixtures for reconciliation, not destructive replacement.

## Confidence

★★★★☆ returned aggregate; ★★☆☆☆ comparison when parameter scopes differ.

## Graph and Warehouse Mapping

Append `team_season_stat_snapshot` with long metric children. Graph reifies snapshot to avoid timeless aggregate edges.

## Inference, Redundancy, and Engineering Notes

Can create feature vectors, not causal claims. Overlaps standings and fixture statistics at different grains; keep all scopes explicit. Index team/league/season/as-of/retrieval.
