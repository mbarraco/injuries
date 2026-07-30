# Fixture

## Purpose
Represent a scheduled match and its evolving reported state.

## Overview
`fixture.id` is the central stable join key for match detail and intelligence products.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Identity and Lifecycle
Suggested table/node: `fixture` / `(:Fixture {source, api_id})` with revisions across scheduled, live, interrupted, and settled state.

## Properties, Relationships, and Producers
`/fixtures` produces identity/time/status/score and home-away roles; detail endpoints create event, selection, performance, and statistic children; injuries/predictions/odds reference it.

## Historical Behavior, Confidence, and Inference
★★★★★ ID/roles; state is snapshot evidence. Re-fetch terminal fixtures before final analytics and keep revision lineage.
