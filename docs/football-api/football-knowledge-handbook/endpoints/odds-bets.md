# Odds Bets Knowledge Domain

## Purpose
Provide reference identities for betting markets and selections used in odds responses.

## Overview
`/odds/bets` documents provider market vocabulary; its terms are not universal cross-bookmaker semantics without explicit mapping.

## Table of Contents
Reference, authority, mapping.

## Knowledge Produced
Bet/market reference IDs and labels; primary `BetMarketReference`.

## Relationships, Grain, and Time
One provider market reference, keyed by returned ID; slowly changing snapshot.

## Authority, Missing Facts, and Joins
Authoritative for provider labels; missing quote values, settlement conventions, and availability. Join odds by returned market/bet IDs.

## Download, Freshness, Confidence, and Model
Cold-start/periodic refresh; ★★★★★ reference identity. Store normalized mapping separately from raw vendor label.

## Inference, Redundancy, and Engineering Notes
Market normalization is local modeling work; retain the raw ID/label so it can be revised.
