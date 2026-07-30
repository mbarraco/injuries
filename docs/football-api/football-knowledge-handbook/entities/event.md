# Fixture Event

## Purpose
Represent one reported timeline incident in a fixture.

## Overview
There is no assumed stable event ID; identity is scoped to fixture and response revision.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
`/fixtures/events` produces time, type, detail, team and player context. Suggested `fixture_event` table and reified graph node linked to fixture/team/player.

## Historical Behavior, Confidence, and Inference
Live/revisionable; ★★★★☆ after settlement. Event order supports a reported timeline, not unreported actions or medical causality.
