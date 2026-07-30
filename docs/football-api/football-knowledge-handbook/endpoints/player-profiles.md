# Player Profiles Knowledge Domain

## Purpose
Bulk-discover player identity profiles.

## Overview
`/players/profiles` provides a list of available player profiles and is an identity acquisition producer, not a performance fact source.

## Table of Contents
Identity, authority, mapping.

## Knowledge Produced
Player profile identity/properties; primary `Player`, secondary country/birth metadata.

## Relationships Created
Profile references only; no team/league relationship should be invented from a bulk profile.

## Grain, Keys, and Time
One player profile; `player.id` is stable identifier; slowly changing, pagination-scoped snapshot.

## Authority, Facts Missing, and Joins
Authoritative for returned profile fields; missing fixture performance, roster, and career movement. Join all player-referencing endpoint families by ID.

## Download, Freshness, Confidence, and Model
Paginate cautiously, record truncation/completeness, refresh profiles periodically. ★★★★★ ID; ★★★★☆ returned mutable attributes.

## Inference, Redundancy, and Engineering Notes
Complements `/players` targeted/scoped results. It expands identity coverage but cannot prove analytical coverage.
