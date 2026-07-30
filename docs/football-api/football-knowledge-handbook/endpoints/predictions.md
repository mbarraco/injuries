# Predictions Knowledge Domain

## Purpose

Capture the provider’s pre-match assessment as a versioned intelligence product.

## Overview

`/predictions` is authoritative only for what the provider predicted and its returned comparative inputs. It is never authoritative for what will happen or for causal football knowledge.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Fixture-scoped predicted outcomes, advice, percentage-like assessments, comparison values, and returned team/league context.

## Primary and Secondary Entities

Primary: `PredictionSnapshot`; secondary: `Fixture`, `Team`, `LeagueSeason`, provider comparison measures.

## Relationships, Grain, and Keys

One prediction response per fixture × retrieval time × payload hash. Fixture ID is foreign key; output keys are provider vocabulary and should be stored flexibly.

## Temporal Semantics and Authority

Mutable pre-match snapshot. Authoritative for provider output at retrieval time; not for future outcome, market probability, or independently verified team strength.

## Facts Learned and Missing

Learns provider assessment. Does not learn bookmaker prices, lineup-confirmed availability, or a reproducible model specification.

## Join, Download, Freshness, and History

Fetch for scheduled fixtures within a defined horizon; snapshot before kickoff and retain all changes. Join to final fixture result only for retrospective calibration.

## Confidence

★★★★★ prediction was returned; ☆☆☆☆☆ prediction as fact about future result.

## Graph and Warehouse Mapping

`prediction_snapshot(fixture_id, retrieved_at, payload_hash, payload)` plus extracted metrics. Graph `PredictionSnapshot-[:ABOUT]->Fixture`.

## Inference, Redundancy, and Engineering Notes

Calibration metrics are derived and must use prediction-time snapshots, not a later overwritten value. Odds are distinct market evidence and should not be blended without timestamp alignment.
