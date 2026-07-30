# Entity Taxonomy

## Purpose

List the entity classes an ingestion agent should create.

## Overview

This is a controlled vocabulary, not a promise that every class has a standalone endpoint.

## Table of Contents

1. Identity entities
2. Scoped entities
3. Event entities

| Class | Category | Preferred evidence |
|---|---|---|
| Country, Timezone | reference | catalogue endpoints |
| League, Season, Coverage | competition catalogue | leagues and seasons |
| Team, Venue, Coach | organization | teams, venues, coachs |
| Player | person | players, players/profiles |
| SquadMembership | team selection snapshot | players/squads |
| Fixture, Round | competition event | fixtures, fixtures/rounds |
| LineupSelection, PlayerPerformance | match participation | fixture details |
| StandingSnapshot, TeamSeasonStatistic | aggregate | standings, teams/statistics |
| Transfer, TrophyAward, SidelinedPeriod | career history | transfers, trophies, sidelined |
| AvailabilityObservation | fixture-scoped availability | injuries |
| OddsQuote, Prediction | external/provider intelligence | odds, predictions |
