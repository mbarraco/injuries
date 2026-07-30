# Seasons Knowledge Domain

## Purpose

Expose the provider’s globally recognized season values for catalogue and query planning.

## Overview

`/seasons` is a reference list. A season number becomes a football scope only when paired with a league.

## Table of Contents

1. Knowledge and grain
2. Authority and limitations
3. Engineering mapping

## Knowledge Produced

Supported season-year values.

## Primary and Secondary Entities

Primary: `SeasonReference`. Secondary: `LeagueSeason` from `/leagues`.

## Relationships, Grain, and Keys

One row per returned year. It has no sufficient football foreign key by itself; create `LeagueSeason` only after joining `league.id`.

## Temporal Semantics and Authority

Slowly changing reference list. Authoritative for supported season parameter values, not for a league’s participation, format, dates, or coverage.

## Facts Learned and Missing

Learns the query vocabulary. Cannot answer “what was the 2020 season?” without competition context.

## Join, Download, Freshness, and History

Use as validation/supporting discovery, refresh occasionally, retain snapshots. `/leagues` is the authority for an actual league-season association.

## Confidence

★★★★★ for returned allowed values; ☆☆☆☆☆ for a universal season entity.

## Graph and Warehouse Mapping

Optional `season_reference(year)` dimension; use `league_season(league_id, season)` for facts.

## Inference, Redundancy, and Engineering Notes

Calendar-year and cross-year competitions make year-only joins unsafe. It overlaps `/leagues.seasons[]`; prefer the latter for crawling.
