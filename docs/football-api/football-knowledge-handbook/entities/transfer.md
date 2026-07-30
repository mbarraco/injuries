# Transfer

## Purpose
Represent a provider-reported player movement event.

## Overview
No documented stable transfer ID; use a collision-aware natural event key plus raw payload provenance.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
`/transfers` creates player, source-team, destination-team, date, and type evidence. Reify `Transfer` in the graph and retain `from_team_id`, `to_team_id`, date, type in `fact_transfer`.

## Historical Behavior, Confidence, and Inference
Historical; ★★★★★ returned parties/date. Membership interval is inferred only and does not prove registration or appearance.
