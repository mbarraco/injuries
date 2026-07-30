# Source and Change Policy

## Purpose

Keep the handbook accurate as API-Football changes without erasing observed history.

## Overview

The official v3 documentation establishes documented capability; the project’s raw cache and append-only logbook establish what was observed under a particular plan and date. Neither source substitutes for the other.

## Table of Contents

1. Evidence hierarchy
2. Change workflow
3. Documentation assertions

## Evidence Hierarchy

1. Retained raw response plus request scope establishes an observed fact.
2. Official provider documentation establishes intended endpoint/field capability.
3. Project logbook records dated operational behavior and discrepancies.
4. This handbook synthesizes those sources and must label inference.

## Change Workflow

When an endpoint appears, changes, or disagrees with observed behavior: add a dated logbook entry; preserve response evidence; update the endpoint profile, matrix, crawl plan, and schema guidance; add a regression test for client/parser behavior where code changes. Never silently rewrite a prior measured claim.

## Assertion Rules

Use “documented” for provider claims, “observed” for cached experiments, and “inferred” for derivations. State query scope and retrieval time when a claim could vary by competition, season, plan, or API revision.
