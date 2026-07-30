# Squads Knowledge Domain

## Purpose

Describe player selection in a returned team or player roster context.

## Overview

`/players/squads` creates roster membership observations. It is valuable for current/queried squad composition but is not a contractual registration ledger and must be timestamped as a snapshot.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Players associated with a requested team, or teams associated with a requested player, plus available player presentation attributes.

## Primary and Secondary Entities

`SquadMembershipSnapshot` is primary evidence; `Player` and `Team` are referenced entities.

## Relationships, Grain, and Keys

One membership observation per player × team × query scope × retrieval time. Use provider IDs; preserve the parameters because the same response shape supports reverse lookup.

## Temporal Semantics and Authority

Snapshot. Authoritative for the roster association returned at retrieval time; not authoritative for effective start/end dates, appearances, loans, or registration status.

## Facts Learned and Missing

Learns who the provider associated with a squad. Does not identify starting XI, minutes, transfers, or an exact historical roster unless it was observed then.

## Join, Download, Freshness, and History

Fetch for current/relevant teams after team discovery and near transfer windows. Historical reconstruction needs repeated retained snapshots plus fixtures/transfers; do not backfill old rosters from a current snapshot.

## Confidence

★★★★☆ for observed membership; ★★☆☆☆ for implied interval membership.

## Graph and Warehouse Mapping

`squad_membership_snapshot(team_id, player_id, observed_at, query_hash)`. Graph: `(:Team)-[:HAS_SQUAD_MEMBER {observed_at, source}]->(:Player)`.

## Inference, Redundancy, and Engineering Notes

Lineups prove selection for a specific fixture; transfers explain moves; neither is interchangeable with roster snapshots. Index team/player and observed time; append rather than overwrite.
