# Fixture Head-to-Head Knowledge Domain

## Purpose
Retrieve a filtered history of fixtures between two teams.

## Overview
`/fixtures/headtohead` is a convenience projection over match history, not a separate rivalry entity or a replacement for the canonical fixture corpus.

## Table of Contents
History, authority, mapping.

## Knowledge Produced
A team-pair-filtered set of fixture records; primary `HeadToHeadQuerySnapshot`, secondary Fixture and Team.

## Relationships, Grain, and Time
One query snapshot containing fixture rows, keyed by ordered/unordered team pair, parameters, and retrieval time.

## Authority, Missing Facts, and Joins
Authoritative for returned filtered fixtures; missing a formal rivalry definition and complete history guarantee. Join/deduplicate by `fixture.id` against `/fixtures`.

## Download, Freshness, Confidence, and Model
Use targeted analysis/cache repair, not bulk spine crawl. ★★★★☆ returned set under query scope. Store query provenance, not duplicate fixture facts.

## Inference, Redundancy, and Engineering Notes
Can calculate pairwise history only across retained response coverage. `/fixtures` is canonical for fixture identity/state.
