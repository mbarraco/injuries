# Team

## Purpose
Represent a club or national team returned by the provider.

## Overview
Identity uses `team.id`; profile, venue, and competition participation are different time-qualified facts.

## Table of Contents
1. Identity 2. Lifecycle 3. Relationships

## Identity and Lifecycle
Suggested table/node: `team` / `(:Team {source, api_id})` with profile/venue versions. Team name and code are not stable keys.

## Properties, Relationships, and Producers
`/teams` produces profile/venue; fixtures produce home/away role; standings/team statistics produce league-season scope; squads, lineups, transfers, and injuries create related observations.

## Historical Behavior, Confidence, and Inference
★★★★★ ID; ★★★★☆ returned profile; ★★★☆☆ team-venue snapshot. A fixture role proves participation in that fixture, not an all-season roster or ownership relationship.
