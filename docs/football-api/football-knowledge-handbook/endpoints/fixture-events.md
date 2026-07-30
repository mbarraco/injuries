# Fixture Events Knowledge Domain

## Purpose

Record the ordered, atomic timeline of notable match incidents.

## Overview

`/fixtures/events` is the direct event producer for goals, cards, substitutions, VAR-related entries, and other reported incidents. It is not a complete tracking feed and absence of an event cannot prove an action did not occur.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Event time/extra time, team, player, assisting/substituted player, type, detail, comments, and ordering context where returned.

## Primary and Secondary Entities

Primary: `FixtureEvent`; secondary: `Fixture`, `Team`, `Player`.

## Relationships, Grain, and Keys

One returned event observation in one fixture. The endpoint does not guarantee a stable event ID; construct a versioned source key from fixture, sequence, elapsed/extra, type/detail, entities, and payload hash—never assume it is globally immutable.

## Temporal Semantics and Authority

Live then historical revisionable timeline. Authoritative for reported event facts; not for unreported off-ball actions, medical cause, or an exhaustive minute-by-minute state.

## Facts Learned and Missing

Learns scoring, discipline, substitutions, and returned event semantics. Does not reliably provide minutes played without lineup/performance context.

## Join, Download, Freshness, and History

Fetch after fixture IDs exist; poll live fixtures, re-fetch on settlement, and retain revisions. Join to fixtures and player/team identity; compare goal events with fixture scores as a quality check, not a replacement.

## Confidence

★★★★★ returned event identity within payload revision; ★★★★☆ final event list after reconciliation; ★★☆☆☆ inferred reason for substitutions.

## Graph and Warehouse Mapping

`fixture_event(fixture_id, sequence, payload_hash, ...)`; edges `Fixture-HAS_EVENT->FixtureEvent`, `FixtureEvent-INVOLVES->Player/Team`.

## Inference, Redundancy, and Engineering Notes

Starting XI plus substitution-in/out events can derive an estimated participation interval, but stoppage-time, abandoned fixtures, and missing lineup data lower confidence. `/fixtures` overlaps only as an embedded convenience. Index fixture and event ordering fields.
