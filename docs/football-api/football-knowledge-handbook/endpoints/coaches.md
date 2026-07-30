# Coaches Knowledge Domain

## Purpose

Represent coaching identities and returned career/roster associations.

## Overview

The documented `/coachs` producer supplies coach profiles; fixture lineups supply fixture-scoped coaching evidence. Treat spelling of the endpoint as an implementation detail, not an ontology term.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Coach identity/profile and returned team/career associations where available.

## Primary and Secondary Entities

Primary: `Coach`; secondary: `Team`, `CoachTenure`, `FixtureLineup`.

## Relationships, Grain, and Keys

One coach profile or returned association. Use `coach.id` as provider identity; tenure is a sourced, dated relationship only when dates/teams are returned.

## Temporal Semantics and Authority

Profiles and career associations are mutable/historical as returned. Authoritative for returned coach facts, not for legal employment, tactical responsibility, or matchday presence without lineup evidence.

## Facts Learned and Missing

Learns coach identity and available associations. Does not establish complete contracts, interim roles, staff hierarchy, or training responsibility.

## Join, Download, Freshness, and History

Fetch on team/fixture references and periodically for active teams. Join fixture lineup coach references to establish match-specific context. Preserve career snapshots.

## Confidence

★★★★★ ID; ★★★★☆ returned team association; ★★★☆☆ inferred tenure interval.

## Graph and Warehouse Mapping

`coach`, `coach_profile_version`, `coach_team_observation`, `fixture_team_coach`. Reify tenure for dates/source.

## Inference, Redundancy, and Engineering Notes

Consecutive fixture lineup appearances can evidence practical matchday management but not a contract. `/trophies` and `/sidelined` can reference coaches and enrich career history.
