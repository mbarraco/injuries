# Historical Backfill

## Purpose

Build a season-by-season historical corpus without implying uniform coverage.

## Overview

The catalogue’s per-season coverage flags form the initial work list. They are signals of supported features, not substitutes for validation. Historical depth varies by competition and feature.

## Table of Contents

1. Work-list construction
2. Validation
3. Recovery

## Procedure

1. Read every `league.seasons[]` entry and persist flags by `(league_id, season, feature)`.
2. Choose scope deliberately: domestic leagues, international competitions, or both. Do not use country-only discovery for world-scoped UEFA competitions.
3. Fetch fixture and availability spines separately for every eligible scope. Record successful empty responses distinctly from blocked requests.
4. For fixture detail endpoints, schedule work from cached fixture IDs and recompute missing IDs on every restart.
5. Validate foreign-key coverage and truncated pagination before publishing a derived database.

## Historical Reconstruction Limits

Fixture events can reconstruct a match timeline. Fixtures plus standings snapshots can reconstruct a standings *series only if snapshots were retained over time*; a final table does not reveal each historical table state. Transfers can support a tentative career chronology but not prove registration or appearance. Injuries cannot be deterministically reconstructed as spells because their records are fixture-scoped.
