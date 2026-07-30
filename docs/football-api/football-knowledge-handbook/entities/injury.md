# Availability Observation

## Purpose
Represent an API-Football player-fixture availability record without misnaming it an injury spell.

## Overview
The `/injuries` grain is player × fixture, with type and free-text reason; no spell identifier or medical interval is supplied.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
Suggested `availability_observation` fact linked to Player, Fixture, Team, and LeagueSeason. Preserve raw type/reason and normalized classification separately.

## Historical Behavior, Confidence, and Inference
★★★★★ source record; never merge questionable and confirmed absence counts. Spell reconstruction is a low-confidence derived layer with explicit gap rules.
