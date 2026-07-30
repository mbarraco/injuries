# Fixture Rounds Knowledge Domain

## Purpose
List competition round labels and optionally their dates for a league-season.

## Overview
`/fixtures/rounds` is a schedule partition/discovery producer, not an authority for every fixture or competition format rule.

## Table of Contents
Rounds, authority, mapping.

## Knowledge Produced
Round name and optional dates under league-season scope; primary `RoundReference`.

## Relationships, Grain, and Time
One league-season × round reference, key `(league_id, season, round_label)`; schedule snapshot.

## Authority, Missing Facts, and Joins
Authoritative for returned labels/dates; missing match result and full fixture identity. Join `/fixtures` for actual fixture-round membership.

## Download, Freshness, Confidence, and Model
Fetch after catalogue/fixtures and refresh when schedules change. ★★★★☆ returned reference. Store revisioned round reference.

## Inference, Redundancy, and Engineering Notes
Useful to shard fixture work. Do not assume labels sort chronologically without returned dates or fixture order.
