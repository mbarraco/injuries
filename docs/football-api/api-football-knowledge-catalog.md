# API-Football Knowledge Catalog

> **Purpose**
>
> This document is intended for an autonomous ingestion agent. Rather than
> documenting the HTTP API, it describes **what knowledge can be acquired**
> from each endpoint, how entities relate to each other, and how to maximize
> data extraction.

## Knowledge Graph

```text
Countries
    │
    ▼
Leagues
    │
    ▼
Teams ─────────────┐
    │              │
    ▼              ▼
Players        Fixtures
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
     Events   Lineups   Player Stats
        │          │          │
        └──────────┼──────────┘
                   ▼
               Injuries
```

---

# GET /leagues

## Purpose
Discover all competitions, seasons, and coverage.

## Primary entities
- League
- Country
- Season

## Knowledge extracted
- League metadata
- Competition type
- Country
- Available seasons
- Coverage capabilities
- Logos

## Join keys
- `league.id`

## Relationships
- League → Country
- League → Season

## Download strategy
- Download once initially.
- Refresh weekly or when new seasons begin.

## Missing information
- Teams
- Fixtures
- Standings

---

# GET /teams

## Purpose
Retrieve clubs and national teams.

## Knowledge extracted
- Team identity
- Country
- Foundation year
- Club code
- Logo
- Stadium (venue)

## Join keys
- `team.id`
- `venue.id`

## Relationships
- Team → Venue
- Team → League (when queried by league)

## Download strategy
- Once per league and season.
- Refresh before every season.

---

# GET /teams/statistics

## Purpose
Season aggregates for a team.

## Knowledge extracted
- Goals scored/conceded
- Home/Away splits
- Form
- Biggest wins/losses
- Clean sheets
- Failed to score
- Cards by minute
- Lineups used

## Grain
One record per (team, league, season).

---

# GET /teams/seasons

## Purpose
Enumerate every season available for a team.

## Join key
- team.id

Useful for historical crawling.

---

# GET /teams/countries

## Purpose
Enumerate countries supported by team endpoints.

Useful for discovery.

---

# GET /venues

## Knowledge extracted
- Venue
- City
- Capacity
- Surface
- Images

Relationships:
- Venue ← Team

---

# GET /standings

## Grain
League standings for one season.

Knowledge:
- Rank
- Points
- Wins
- Draws
- Losses
- Goals
- Form

---

# GET /fixtures

## Purpose
Master table of matches.

Knowledge extracted
- Fixture
- Date/time
- Referee
- Venue
- Status
- League
- Home team
- Away team
- Score
- Penalties

Join keys
- fixture.id

This endpoint is the backbone of the entire dataset.

---

# GET /fixtures/headtohead

Knowledge:
Historical meetings between two teams.

Useful for:
- Rivalries
- Historical performance
- Prediction features

---

# GET /fixtures/statistics

Knowledge
- Possession
- Shots
- Fouls
- Passes
- Offsides
- Corners
- Expected match statistics

Grain:
Fixture × Team

---

# GET /fixtures/events

Knowledge
- Goals
- Cards
- Substitutions
- VAR
- Penalties
- Own goals

Grain:
One event.

Forms a complete timeline.

---

# GET /fixtures/lineups

Knowledge
- Starting XI
- Bench
- Formation
- Coach

Relationships
Fixture → Team → Player

---

# GET /fixtures/players

Knowledge
- Minutes
- Goals
- Assists
- Rating
- Passes
- Tackles
- Duels
- Saves
- Dribbles
- Cards

Grain
Fixture × Player

This is the richest player-performance endpoint.

---

# GET /injuries

## Purpose
Retrieve player unavailability.

Knowledge
- Injured player
- Team
- Fixture
- Competition
- Injury reason

Join keys
- player.id
- fixture.id
- team.id
- league.id

Missing
- Recovery date
- Severity
- Medical diagnosis

---

# Recommended Crawl Order

1. /leagues
2. /teams
3. /teams/seasons
4. /fixtures
5. /fixtures/events
6. /fixtures/lineups
7. /fixtures/players
8. /fixtures/statistics
9. /standings
10. /teams/statistics
11. /injuries

---

# Entity Catalog

| Entity | Primary Endpoint |
|---------|------------------|
| League | /leagues |
| Team | /teams |
| Player | /fixtures/players |
| Fixture | /fixtures |
| Venue | /venues |
| Injury | /injuries |
| Standing | /standings |
| Event | /fixtures/events |
| Lineup | /fixtures/lineups |
| Team Statistics | /teams/statistics |

---

# Notes for an Autonomous Agent

- Prefer immutable IDs over names.
- Treat `/fixtures` as the central fact table.
- Build historical data season-by-season.
- Enrich fixtures with events, lineups, player statistics, and injuries.
- Refresh static metadata infrequently and fixture-related endpoints after matches.
- Maintain referential integrity using IDs.
