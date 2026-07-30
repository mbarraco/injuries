# Odds Knowledge Domain

## Purpose

Capture bookmaker market quotes and the reference vocabularies needed to interpret them.

## Overview

`/odds` and `/odds/live` produce timestamped market observations; `/odds/bookmakers`, `/odds/bets`, and `/odds/live/bets` produce vocabularies; `/odds/mapping` links provider fixture identifiers. A quote is not a probability, prediction, or settled result.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Bookmaker, bet/market, value/selection, fixture or scoped query context, and live/pre-match quote observations; reference bookmaker and bet identities; cross-provider mapping where returned.

## Primary and Secondary Entities

Primary: `OddsQuote`, `Bookmaker`, `BetMarket`, `OddsMapping`; secondary: `Fixture`, `LeagueSeason`.

## Relationships, Grain, and Keys

One quote per fixture × bookmaker × market × selection × retrieval time. Reference identities use returned IDs. Mapping is a source-specific relation, not a replacement fixture key.

## Temporal Semantics and Authority

Highly mutable snapshot. Authoritative for returned provider/bookmaker quote at retrieval; not for fair probability, availability at another time, or actual settlement.

## Facts Learned and Missing

Learns market observations and supplied vocabularies. Does not learn transaction volume, consumer access, margin model, or guarantee that a market was continuously offered.

## Join Opportunities

Join fixture IDs, bookmakers/bets by returned IDs, and final fixture result for evaluation. Align to event/prediction time before comparative analysis.

## Download Strategy, Freshness, and History

Refresh reference vocabularies infrequently. Snapshot pre-match odds on a scheduled horizon; poll live odds only for active fixtures under a defined budget. Append every changed quote; never overwrite history. Use mapping only to link external provider context.

## Confidence

★★★★★ quote/reference as returned; ★★★☆☆ implied market availability interval; ★☆☆☆☆ quote as forecast truth.

## Graph and Warehouse Mapping

`odds_quote`, `bookmaker`, `bet_market`, `odds_mapping`; graph `Bookmaker-[:QUOTED {value, observed_at}]->Market-[:FOR_FIXTURE]->Fixture`.

## Inference, Redundancy, and Engineering Notes

Implied probabilities and overround are deterministic calculations from compatible decimal quotes but require market normalization and timestamp grouping. Predictions overlap only as another provider assessment. Partition quotes by fixture date/retrieval date and index fixture/bookmaker/market/time.
