# Live Odds Knowledge Domain

## Purpose
Capture live bookmaker market quotes during active fixtures.

## Overview
`/odds/live` has the same quote semantics as pre-match odds with higher churn and stronger timestamp requirements.

## Table of Contents
Quotes, authority, mapping.

## Knowledge Produced
Live `OddsQuote` observations by fixture, bookmaker, bet/market, selection, and retrieval time.

## Relationships, Grain, and Time
One quote snapshot per fixture × bookmaker × market × selection × time. All keys must include quote observation time.

## Authority, Missing Facts, and Joins
Authoritative for returned live quote; missing continuous market history, volume, and settlement. Join fixture status/events only with timestamp alignment.

## Download, Freshness, Confidence, and Model
Poll active fixtures within budget, append changes, reconcile shutdown/settlement. ★★★★★ quote observation. Use shared `odds_quote` fact with `phase='live'`.

## Inference, Redundancy, and Engineering Notes
Price movement is a deterministic series only from retained snapshots; causality from events is speculative. Do not overwrite pre-match odds.
