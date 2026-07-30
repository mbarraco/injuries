# Venue

## Purpose
Represent a football location and its returned profile.

## Overview
Venue identity uses `venue.id` where present; team association and fixture location are separate relationships.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Properties, Producers, and Model
`/venues` and `/teams` produce profile context; `/fixtures` produces match context. Suggested table/node: `venue` / `(:Venue {source, api_id})` plus versioned attributes.

## Historical Behavior, Confidence, and Inference
★★★★★ returned ID; ★★★★☆ profile; fixture venue is stronger evidence than a team profile for where a match occurred. Do not infer permanent home ground from one fixture.
