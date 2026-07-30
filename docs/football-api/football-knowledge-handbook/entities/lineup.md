# Lineup Selection

## Purpose
Represent a player’s starting or substitute selection for a fixture.

## Overview
Selection is fixture-scoped and distinct from performance.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
`/fixtures/lineups` creates fixture-team-player role, position/grid, formation, and coach context. Store a revisioned `lineup_member` fact.

## Historical Behavior, Confidence, and Inference
★★★★★ selection as returned; appearance/minutes require `/fixtures/players` or qualified event inference.
