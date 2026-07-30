# Venues Knowledge Domain

## Purpose

Represent playing locations and their physical profile.

## Overview

`/venues` produces venue discovery and profile data; fixture responses provide event-specific venue context. A team’s returned venue is not evidence that every fixture was played there.

## Table of Contents

1. Knowledge and grain
2. Authority and limitations
3. Engineering mapping

## Knowledge Produced

Venue identity, name, address, city, capacity, surface, and image where returned.

## Primary and Secondary Entities

Primary: `Venue`; secondary: `Team` and `Fixture` references.

## Relationships, Grain, and Keys

One venue profile; `venue.id` is the join key. Model team association and fixture usage as separate time-qualified relationships.

## Temporal Semantics and Authority

Slowly changing profile. Authoritative for returned venue attributes, not for historical capacity, ownership, or a fixture’s actual location unless fixture context agrees.

## Facts Learned and Missing

Learns provider venue metadata. Does not learn attendance, pitch conditions, stadium construction history, or legal address history.

## Join, Download, Freshness, and History

Discover by ID/search or from teams/fixtures; refresh infrequently and version changes. Use `/fixtures` for fixture venue context and `/teams` for organization association.

## Confidence

★★★★★ venue ID; ★★★★☆ returned profile; ★★★☆☆ team-to-venue snapshot.

## Graph and Warehouse Mapping

`venue`, `venue_profile_version`, `team_venue_snapshot`, `fixture_venue`. Edges: `Team-[:USES_VENUE]->Venue`, `Fixture-[:PLAYED_AT]->Venue`.

## Inference, Redundancy, and Engineering Notes

Venue changes can explain scheduling anomalies only as a hypothesis. Index `venue_id`; do not equate venue name text across vendors without reconciliation evidence.
