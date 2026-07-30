# Trophies Knowledge Domain

## Purpose

Represent provider-reported honours associated with players or coaches.

## Overview

`/trophies` produces career-award history, not a match-by-match proof of contribution. Attribute awards to people exactly as returned and retain competition/season context.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Award name, country, season, place, league, and returned player/coach association.

## Primary and Secondary Entities

Primary: `TrophyAward`; secondary: `Player` or `Coach`, `League`, `SeasonReference`.

## Relationships, Grain, and Keys

One reported award association. No assumed global award ID: use recipient, award/league/country, season, place, and payload hash with collision handling.

## Temporal Semantics and Authority

Historical, potentially corrected. Authoritative for the returned attribution; not for game participation, medal eligibility, team roster, or award criteria.

## Facts Learned and Missing

Learns a reported honour. Does not learn appearances in that winning campaign or exact award ceremony date.

## Join, Download, Freshness, and History

Fetch per player/coach as a career enrichment; refresh periodically. Join recipients by IDs and league context only when IDs exist. Preserve raw labels.

## Confidence

★★★★☆ returned attribution; ★★☆☆☆ inferred team association.

## Graph and Warehouse Mapping

`trophy_award` fact and `Award` dimension; graph `Player|Coach-[:RECEIVED]->TrophyAward`.

## Inference, Redundancy, and Engineering Notes

Trophies can enrich a career graph but cannot prove club membership on any date. Transfers, squads, and fixtures provide separate evidence.
