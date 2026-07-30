# Timezones Knowledge Domain

## Purpose
Provide the timezone vocabulary accepted by provider queries.

## Overview
`/timezones` is a reference producer, not an authority for a fixture’s actual local venue time.

## Table of Contents
Reference, authority, mapping.

## Knowledge Produced
One supported timezone value per row; primary entity `TimezoneReference`, stable identifier the returned value.

## Relationships Created
None intrinsically; query metadata may reference a timezone.

## Grain, Temporal Semantics, and Authority
Reference snapshot; slowly changing; authoritative only for provider-supported values.

## Facts Learned, Missing, and Joins
Learns valid vocabulary; misses venue timezone and historical daylight rules. Joins only to request/provenance records.

## Download Strategy, Freshness, and History
Cold-start and occasional refresh; version snapshots.

## Confidence, Graph, Warehouse, and Inference
★★★★☆ vocabulary. `timezone_reference` dimension; no football graph edge. It can validate a query, not convert football facts without explicit timestamp rules.

## Redundancy and Engineering Notes
Overlaps request configuration only. Index canonical string and retain raw response.
