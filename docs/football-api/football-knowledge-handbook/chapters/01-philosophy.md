# Knowledge-First Philosophy

## Purpose

Establish the modeling rules used by every chapter.

## Overview

An endpoint is not an entity. `/fixtures/events` is a producer of event observations; `/fixtures` is a producer of fixture identity, schedule, result, and embedded match context. Modeling around paths obscures overlap and creates duplicate “truth” tables.

## Table of Contents

1. Authority
2. Grain
3. Time
4. Inference

## Rules

1. Model the **grain before the columns**. An injury response is a player–fixture availability observation, not a clinical injury spell.
2. Keep raw vendor strings and IDs beside normalized classifications. Normalization is a local interpretation.
3. Make query scope explicit. A player season statistic is scoped to player, team, league, and season; it is not a career fact.
4. Preserve retrieval time and response version evidence. Mutable fixtures and provider predictions need history.
5. Use an authority matrix instead of copying values between overlapping endpoints. The most convenient endpoint is not automatically authoritative.

## Confidence Scale

| Rating | Meaning |
|---|---|
| ★★★★★ | Direct vendor observation at its declared grain |
| ★★★★☆ | Direct observation with known scope or coverage limits |
| ★★★☆☆ | Deterministic derivation from retained observations |
| ★★☆☆☆ | Heuristic reconstruction requiring assumptions |
| ★☆☆☆☆ | Plausible but unvalidated inference |
