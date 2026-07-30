# Odds Bookmakers Knowledge Domain

## Purpose
Provide reference identities for bookmakers used by odds responses.

## Overview
`/odds/bookmakers` is a low-churn vocabulary producer, not an endorsement, market-availability, or quote endpoint.

## Table of Contents
Reference, authority, mapping.

## Knowledge Produced
Bookmaker ID/name reference records; primary `Bookmaker`.

## Relationships, Grain, and Time
One provider bookmaker reference. Key is returned bookmaker ID; slowly changing snapshot.

## Authority, Missing Facts, and Joins
Authoritative for provider bookmaker vocabulary; missing every quote and jurisdiction/access condition. Join odds by bookmaker ID.

## Download, Freshness, Confidence, and Model
Cold-start plus occasional refresh; ★★★★★ ID/name as returned. Store `bookmaker` and profile versions.

## Inference, Redundancy, and Engineering Notes
Do not infer that a bookmaker offered a market because it appears in reference vocabulary.
