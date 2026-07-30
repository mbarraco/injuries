# Live Odds Bets Knowledge Domain

## Purpose
Provide market reference vocabulary for live odds.

## Overview
`/odds/live/bets` is reference metadata supporting interpretation of `/odds/live` quotes.

## Table of Contents
Reference, authority, mapping.

## Knowledge Produced
Live-market identifiers and labels; primary `LiveBetMarketReference`.

## Relationships, Grain, and Time
One returned market reference; key is provider market ID; slowly changing snapshot.

## Authority, Missing Facts, and Joins
Authoritative for returned vocabulary; missing quotes, prices, and availability. Join live odds by provider market ID.

## Download, Freshness, Confidence, and Model
Refresh with odds reference data; ★★★★★ raw reference. Store separate source/phase metadata when IDs overlap pre-match markets.

## Inference, Redundancy, and Engineering Notes
Do not assume live and pre-match market labels are equivalent merely because they look similar.
