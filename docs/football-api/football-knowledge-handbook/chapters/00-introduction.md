# Introduction

## Purpose

Define what this handbook promises: an engineering model of the football knowledge API-Football can emit.

## Overview

API-Football emits observations about a changing sporting world. A response may identify an entity, report a match state, publish a season aggregate, or expose a provider-generated assessment. These are different epistemic objects and must not be collapsed into one generic “API data” table.

## Table of Contents

1. [Philosophy](01-philosophy.md)
2. [Ontology](02-football-ontology.md)
3. [Taxonomy](03-taxonomy.md)

## Scope

The handbook covers the documented v3 surface: catalogue and service metadata; teams, venues, coaches, and players; competition and fixture facts; availability, transfers, trophies, and sidelining; predictions and odds. It also records endpoint families that overlap or are discovery aids rather than domain facts.

## Non-goals

It is not an OpenAPI definition, SDK guide, or promise that a queried fact is available for every league. It does not invent contract, wage, registration, medical, tracking, or training data that API-Football does not provide.

## Evidence Classes

| Class | Meaning | Storage rule |
|---|---|---|
| Observed fact | Returned as a dated response | Preserve raw response and retrieval time |
| Catalog capability | `leagues.seasons.coverage` advertises availability | Treat as a crawl work-list input, not a row guarantee |
| Snapshot aggregate | Current response summarizes a scope | Version by query parameters and retrieval time |
| Derived inference | Computed from two or more observations | Store derivation, inputs, and confidence |
