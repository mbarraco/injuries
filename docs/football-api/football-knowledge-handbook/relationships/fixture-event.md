# Fixture–Event Relationship

## Purpose
Attach reported atomic incidents to their fixture timeline.

## Overview
Every event belongs to one fixture response; entities involved can be player/team references and may be absent for some types.

## Table of Contents
1. Meaning 2. Evidence 3. Model

## Semantics and Evidence
`/fixtures/events` is the direct producer. Event sequence is revisioned and endpoint-local because no global event ID is assumed.

## Cardinality, History, and Mapping
One Fixture has many FixtureEvents. Store fixture ID, ordering/time, type/detail, involved IDs, revision hash. Graph `Fixture-HAS_EVENT->FixtureEvent` with optional `INVOLVES` edges.
