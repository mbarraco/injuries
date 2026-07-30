# Odds Mapping Knowledge Domain

## Purpose
Link API-Football fixture identity to an external odds-provider identifier where returned.

## Overview
`/odds/mapping` is an integration mapping, not a second canonical fixture identity.

## Table of Contents
Mapping, authority, mapping model.

## Knowledge Produced
Provider fixture-ID correspondences; primary `ExternalFixtureMapping`.

## Relationships, Grain, and Time
One source fixture × external provider fixture mapping, keyed by source/provider/external ID and retrieval revision.

## Authority, Missing Facts, and Joins
Authoritative only for returned correspondence; missing semantic identity proof, lifecycle guarantees, and external provider data. Join to fixture by source fixture ID.

## Download, Freshness, Confidence, and Model
Fetch when integrating odds, preserve mapping history; ★★★★☆ returned mapping. Store namespace explicitly.

## Inference, Redundancy, and Engineering Notes
Never collapse external and API-Football IDs into one identifier. Mapping changes are data-quality events to audit.
