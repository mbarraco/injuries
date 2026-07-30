# League

## Purpose
Represent a competition identity with country/type context and season-scoped capability.

## Overview
`league.id` identifies the provider competition; `season` must be scoped by league.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Identity and Lifecycle
Suggested tables/nodes: `league`, `league_season`, `league_season_coverage_snapshot`; `(:League)-[:HAS_SEASON]->(:LeagueSeason)`.

## Properties, Relationships, and Producers
`/leagues` produces catalogue and advertised coverage; `/fixtures`, `/standings`, and scoped endpoints produce actual facts.

## Historical Behavior, Confidence, and Inference
★★★★★ ID/returned season link; coverage flags are ★★★★☆ crawl evidence, never guaranteed records. Explicitly include world-scoped competitions in discovery policy.
