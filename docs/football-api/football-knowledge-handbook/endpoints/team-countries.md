# Team Countries Knowledge Domain

## Purpose
Discover country values supported by team queries.

## Overview
`/teams/countries` is query capability metadata, not a country ontology.

## Table of Contents
Discovery, authority, mapping.

## Knowledge Produced
One team-query country value; primary `TeamCountryCapability`.

## Relationships Created
No direct team membership edge.

## Grain, Keys, and Time
One country capability row, key canonical returned label/code; slowly changing snapshot.

## Authority, Facts Missing, and Joins
Authoritative for endpoint support; not for a team’s country. Join `/countries` only as vocabulary reconciliation.

## Download, Freshness, Confidence, and Model
Cold-start/occasional refresh; ★★★★☆ provider capability. Store capability reference with retrieval time.

## Inference, Redundancy, and Engineering Notes
Useful to bound discovery, never to exclude world-scoped competitions. Overlaps `/countries` but has a different semantic role.
