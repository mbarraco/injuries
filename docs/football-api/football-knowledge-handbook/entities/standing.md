# Standing Snapshot

## Purpose
Represent one provider table state for a competition scope.

## Overview
Rank and points are snapshot values, not timeless team attributes.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
`/standings` creates team rows per league-season/group/retrieval time. Use parent `standing_snapshot` and child rows, or reified graph nodes.

## Historical Behavior, Confidence, and Inference
★★★★★ returned table at retrieval. A historical progression requires retained snapshots or explicit full rules/fixtures.
