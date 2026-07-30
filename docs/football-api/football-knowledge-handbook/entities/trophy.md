# Trophy Award

## Purpose
Represent a provider-reported honour associated with a player or coach.

## Overview
Award association does not establish match participation or team membership.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
`/trophies` provides award name/context/season/place. Use a `trophy_award` fact with a collision-aware natural key and recipient edge.

## Historical Behavior, Confidence, and Inference
Historical, ★★★★☆ attribution as returned. Do not infer a winning-campaign roster or minutes.
