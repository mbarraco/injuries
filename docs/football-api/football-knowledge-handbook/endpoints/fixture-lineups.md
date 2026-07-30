# Fixture Lineups Knowledge Domain

## Purpose

Describe team selection, formation, player placement, substitutes, and coach context for one fixture.

## Overview

`/fixtures/lineups` establishes who was selected and in what returned role. Selection is not appearance: a bench player may never enter, and a named starter may have exceptional match circumstances.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Formation, coach, starting XI, substitutes, player position/grid, and returned team colors/context.

## Primary and Secondary Entities

Primary: `FixtureTeamLineup`, `LineupSelection`; secondary: `Fixture`, `Team`, `Player`, `Coach`.

## Relationships, Grain, and Keys

One selection per fixture × team × player × lineup role. Use `(fixture_id, team_id, player_id, role)` plus response revision; preserve player grid/position as fixture-scoped.

## Temporal Semantics and Authority

Pre-match/live/settled revisionable. Authoritative for returned selection, not for exact minutes, tactical intent, or an effective employment relationship.

## Facts Learned and Missing

Learns starting/bench selection and formation. Does not guarantee participation, substitutions, performance, or injury severity.

## Join, Download, Freshness, and History

Fetch near kickoff and settle after match. Join events for substitutions and fixture players for minutes/performance. Re-fetch late changes rather than relying on an early lineup snapshot.

## Confidence

★★★★★ returned selection; ★★★☆☆ starter-to-minute inference; ★☆☆☆☆ formation-to-tactical-style inference.

## Graph and Warehouse Mapping

`fixture_lineup`, `lineup_member`, `fixture_team_coach`; graph `Player-[:SELECTED_FOR {role, position}]->Fixture`.

## Inference, Redundancy, and Engineering Notes

Combining lineup and substitution events supports estimated playing intervals; prefer `/fixtures/players` when reported minutes are available. Index fixture/team/player and retain revisions.
