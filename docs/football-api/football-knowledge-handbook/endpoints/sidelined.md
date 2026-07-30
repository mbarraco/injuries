# Sidelined Knowledge Domain

## Purpose

Represent provider-reported sidelining periods for players or coaches.

## Overview

`/sidelined` is distinct from `/injuries`: it reports a career/history-style absence interval when available, whereas injuries reports fixture-scoped availability. Neither can be silently substituted for the other.

## Table of Contents

1. Knowledge and grain
2. Authority and limits
3. Engineering mapping

## Knowledge Produced

Returned sidelined start/end dates, type, and player or coach context.

## Primary and Secondary Entities

Primary: `SidelinedPeriod`; secondary: `Player`/`Coach`, optional `Team` context.

## Relationships, Grain, and Keys

One returned period. Use an endpoint-derived natural key with raw payload hash; do not assume it identifies the same real-world spell as an injury feed record.

## Temporal Semantics and Authority

Historical interval as returned. Authoritative for provider’s period record; not for fixture-level availability, medical diagnosis, or full recovery certainty.

## Facts Learned and Missing

Learns returned absence dates/type. Does not learn a fixture list, severity, treatment, or guaranteed continuity across sparse periods.

## Join, Download, Freshness, and History

Fetch per person for career enrichment; join fixtures by date range only as an inference. Preserve overlapping/duplicate records for audit.

## Confidence

★★★★☆ returned interval; ★★☆☆☆ fixture misses inferred by date overlap.

## Graph and Warehouse Mapping

`sidelined_period` table; graph `Person-[:WAS_SIDELINED {from,to,type}]->SidelinedPeriod`.

## Inference, Redundancy, and Engineering Notes

It can support temporal alignment with transfers and fixtures, but date overlap does not prove causality. `/injuries` is required for vendor fixture availability and should remain a distinct fact table.
