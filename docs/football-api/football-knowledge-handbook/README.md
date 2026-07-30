# API-Football Football Knowledge Handbook

## Purpose

Provide a durable engineering reference for the *football knowledge* exposed by API-Football v3. It is written for ingestion systems, analytical warehouses, and knowledge graphs; endpoints are treated as producers of evidence, not as the structure of the book.

## Overview

The handbook separates vendor-observed facts, documented capabilities, and derived inferences. It does not treat an API response as complete ground truth: availability is competition-, season-, plan-, and time-dependent. Stable numeric identifiers are the preferred join keys; names are evidence for display and reconciliation only.

## Table of Contents

- [Introduction](chapters/00-introduction.md)
- [Football ontology](chapters/02-football-ontology.md)
- [Endpoint encyclopedia](appendices/endpoint-index.md)
- [Crawl strategy](crawl/cold-start.md)
- [Warehouse design](warehouse/relational-schema.md)
- [Graph design](warehouse/graph-schema.md)
- [Inference catalog](appendices/inference-catalog.md)

## Reading Rules

> **Authority is scoped.** “Authoritative” means the endpoint is the best producer of a stated fact at a stated grain. It does not mean that the API is globally complete or historically immutable.

> **Observed absence is not absence in football.** An empty successful response means no record was returned for that query at that time. It cannot prove that an event, player, injury, or competition did not exist.

## Source Discipline

This book is maintained from the official API-Football documentation and the repository’s cache-first ingestion observations in `logbook/apifootball.md`. When they conflict, retain both claims, label the evidence, and add a dated correction rather than silently rewriting history.
