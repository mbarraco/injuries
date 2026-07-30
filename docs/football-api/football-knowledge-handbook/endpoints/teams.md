# Teams Knowledge Domain

## Purpose

Represent clubs and national teams and their returned venue association.

## Overview

`/teams` is the primary producer of team profiles. When queried by league and season it also evidences a scoped participation set, but profile identity and participation must be stored separately.

## Table of Contents

1. Knowledge and grain
2. Authority and temporal behavior
3. Acquisition and models

## Knowledge Produced

Team identity, display profile, country label, foundation year, code, national flag, logo, and current/returned venue profile.

## Primary and Secondary Entities

Primary: `Team`; secondary: `Venue`, `Country`, `TeamSeasonParticipation`.

## Relationships Created

`Team-[:USES_VENUE]->Venue`, `Team-[:IN_COUNTRY]->Country`, and, under league-season query scope, `Team-[:PARTICIPATES_IN]->LeagueSeason`.

## Grain, Keys, and Identifiers

One returned team profile. `team.id` is the provider join key; `venue.id` is a separate identity where populated. League-season participation uses `(team_id, league_id, season, source_query)`.

## Temporal Semantics and Authority

Identity is enduring; profile and venue are slowly changing. The response is authoritative for the returned profile association, not a historical ownership timeline or legal club identity.

## Facts Learned and Missing

Learns organization metadata and a venue association. Does not prove a squad, coach tenure, player contract, league history, or all-time venue history.

## Join Opportunities

Join to fixtures through home/away team IDs; to standings and team statistics by scoped team ID; to transfers, lineups, injuries, and players as referenced entities.

## Download Strategy, Freshness, and History

Cold start by league-season for participation plus ID discovery. Historical backfill follows selected league seasons. Refresh profiles before/through seasons; re-query affected teams when venue/profile changes matter. Preserve snapshots rather than replacing prior venue links.

## Confidence

★★★★★ team ID; ★★★★☆ profile/venue at retrieval; ★★☆☆☆ historical membership inferred from a single profile.

## Graph and Warehouse Mapping

`team`, `team_profile_version`, `venue`, `team_venue_snapshot`, `team_league_season`. Graph edges include `USES_VENUE {observed_at}` and `PARTICIPATES_IN {source}`.

## Inference, Redundancy, and Engineering Notes

Fixtures and standings can corroborate participation; neither replaces profile authority. Team names are non-unique and mutable—never use them as joins. Index provider IDs and scoped participation keys.
