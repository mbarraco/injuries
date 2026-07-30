# Raw Evidence Store

## Purpose

Specify the durable cache that makes all normalized facts and inferences replayable.

## Overview

Raw data is the authoritative internal record of what the provider returned. The warehouse and graph are projections that can be rebuilt when parsing, classification, or ontology changes.

## Table of Contents

1. Envelope
2. Identity
3. Retention

## Envelope

Persist provider, endpoint, canonical request parameters, retrieval timestamp, HTTP status, classified outcome, relevant rate headers, response body, payload hash, pagination metadata, and truncation flag. Preserve request scope even when the response repeats it.

## Identity and Dedupe

Use a canonical parameter serialization and content hash. A request key identifies a query; a payload hash identifies a revision. Keep both: the same query can change, and identical payloads can be returned by different scopes/times.

## Retention and Access

Compress immutable raw JSON and retain it longer than projections. Separate secrets from logs; the API key belongs in request headers and must never be stored. Redact account information according to operational policy.

## Validation

Reject or explicitly label truncated paginated data before it becomes a denominator or coverage claim. Validate response body error structures before reading `results: 0` as a genuine empty answer.
