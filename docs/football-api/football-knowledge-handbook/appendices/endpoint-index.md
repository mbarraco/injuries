# Endpoint Encyclopedia

## Purpose

Map each documented API-Football v3 endpoint to its knowledge role, authority boundary, and canonical chapter.

## Overview

The path is an implementation locator; the knowledge domain is the design unit. “Direct chapter” pages receive the complete handbook treatment. “Compact profile” entries below still define their grain, authority, and crawl role until a dedicated page is expanded.

## Table of Contents

1. Catalogue and service
2. Organizations and people
3. Competition and matches
4. Career and availability
5. Intelligence

| Domain | Endpoint producer | Grain | Authority | Chapter/profile |
|---|---|---|---|---|
| Service access | `/status` | account snapshot | quota/subscription response | [status](../endpoints/status.md) |
| Reference | `/timezones`, `/countries` | one supported value | vendor reference list | [countries](../endpoints/countries.md) |
| Competition catalogue | `/leagues`, `/seasons` | league; league-season | league metadata and advertised coverage | [leagues](../endpoints/leagues.md), [seasons](../endpoints/seasons.md) |
| Organizations | `/teams`, `/venues`, `/coachs` | entity profile | identity/profile as returned | [teams](../endpoints/teams.md), [venues](../endpoints/venues.md), [coaches](../endpoints/coaches.md) |
| Team scope | `/teams/statistics`, `/teams/seasons`, `/teams/countries` | team-league-season; team-season; country | aggregate/discovery | [team statistics](../endpoints/team-statistics.md) |
| Player scope | `/players`, `/players/profiles`, `/players/seasons`, `/players/teams`, `/players/squads` | player-season-team; profile; career scope; roster snapshot | scoped statistics and profile | [players](../endpoints/players.md), [squads](../endpoints/squads.md) |
| Leaderboards | `/players/topscorers`, `/players/topassists`, `/players/topyellowcards`, `/players/topredcards` | rank within league-season | provider ranking for metric/scope | compact profiles |
| Fixture spine | `/fixtures`, `/fixtures/rounds`, `/fixtures/headtohead` | fixture; round list; historical fixture set | fixture schedule/result and discovery | [fixtures](../endpoints/fixtures.md) |
| Fixture detail | `/fixtures/events`, `/fixtures/statistics`, `/fixtures/lineups`, `/fixtures/players` | event; fixture-team stat; selection; player-fixture performance | direct match evidence | dedicated chapters |
| Competition aggregate | `/standings` | standing snapshot | table as returned for scope | [standings](../endpoints/standings.md) |
| Career history | `/transfers`, `/trophies`, `/sidelined` | transfer; award; sidelined interval | respective provider history | [transfers](../endpoints/transfers.md) |
| Availability | `/injuries` | player-fixture observation | availability labels for returned fixture | [injuries](../endpoints/injuries.md) |
| Provider intelligence | `/predictions` | fixture provider assessment | provider output, not outcome truth | [predictions](../endpoints/predictions.md) |
| Betting intelligence | `/odds`, `/odds/live`, `/odds/bookmakers`, `/odds/bets`, `/odds/mapping`, `/odds/live/bets` | quote/reference/mapping snapshot | bookmaker quote/reference at retrieval time | [odds](../endpoints/odds.md) |

## Compact Profiles

| Endpoint | Knowledge produced | Grain and boundary | Crawl role |
|---|---|---|---|
| `/timezones` | supported timezone identifiers | one timezone string; not fixture local time authority | cache occasionally; use to validate query parameters |
| `/teams/seasons` | seasons associated with a team | team × season; does not prove every competition or match | historical discovery supplement |
| `/teams/countries` | countries usable by team queries | supported country string; not a football federation model | low-cost discovery only |
| `/players/seasons` | seasons associated with a player | player × season; not a complete appearance history | constrain player historical queries |
| `/players/teams` | player career team/season associations | player × team × season | enrich career discovery; do not replace transfers or appearances |
| `/players/profiles` | list of player profiles | one player profile | bulk identity discovery; paginate and preserve coverage scope |
| `/players/top*` | rank by one statistic | league × season × rank | derived leaderboard; do not sum ranks into career totals |
| `/fixtures/rounds` | named rounds and optional dates | league × season × round | fixture work partition/discovery |
| `/fixtures/headtohead` | fixture records between two teams | fixture set for requested pair | relationship history, not a rivalry authority |
| `/odds/bookmakers`, `/odds/bets` | bookmaker/bet vocabularies | reference entity | refresh slowly; preserve IDs |
| `/odds/mapping` | cross-provider fixture mapping | provider fixture mapping | integration aid, not canonical football identity |
| `/odds/live/bets` | live bet vocabularies | reference/snapshot support | refresh with live market workflow |
