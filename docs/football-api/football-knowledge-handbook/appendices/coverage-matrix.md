# Coverage and Authority Matrix

## Purpose

Give an agent one decision table for locating each meaningful fact and understanding its limits.

## Overview

“Historical” means the endpoint can return past data where catalogue/plan coverage permits; it never means all competitions or all time. “Live” means the producer can change while a fixture is active.

## Table of Contents

1. Identity and competition
2. Match facts
3. Career and intelligence

| Knowledge | Authority producer | Historical | Live | Confidence | Boundary |
|---|---|---:|---:|---:|---|
| Supported country/timezone value | `/countries`, `/timezones` | snapshot | no | ★★★★☆ | provider vocabulary only |
| League identity and feature availability | `/leagues` | catalogue | no | ★★★★☆ | capability is not response guarantee |
| League-season association | `/leagues` | yes | no | ★★★★★ | season needs league qualifier |
| Team identity/profile | `/teams` | partial | no | ★★★★☆ | profile not historical membership |
| Venue profile | `/venues` | partial | no | ★★★★☆ | fixture location from fixtures |
| Coach profile | `/coachs` | partial | no | ★★★★☆ | employment not fully modeled |
| Player profile | `/players`, `/players/profiles` | partial | no | ★★★★☆ | field sparsity/versioning |
| Squad membership snapshot | `/players/squads` | observed snapshots | no | ★★★★☆ | not registration interval |
| Player season aggregate | `/players` | where covered | evolving | ★★★★☆ | scoped team/league/season |
| Fixture identity/schedule/result | `/fixtures` | where covered | yes | ★★★★★ | retain revisions |
| Round list | `/fixtures/rounds` | where covered | no | ★★★★☆ | schedule partition only |
| Match timeline | `/fixtures/events` | where covered | yes | ★★★★☆ | reported events only |
| Selection/formation | `/fixtures/lineups` | where covered | pre/live | ★★★★☆ | selection ≠ appearance |
| Player match minutes/performance | `/fixtures/players` | where covered | yes | ★★★★☆ | returned player rows only |
| Team match statistics | `/fixtures/statistics` | where covered | yes | ★★★★☆ | provider measurement labels |
| Standings | `/standings` | where covered | evolving | ★★★★★ | snapshot, not historical series |
| Team season aggregate | `/teams/statistics` | where covered | evolving | ★★★★☆ | scope/as-of dependent |
| Player movement | `/transfers` | yes | no | ★★★★★ | not appearances/contracts |
| Trophy attribution | `/trophies` | yes | no | ★★★★☆ | not participation evidence |
| Sidelined period | `/sidelined` | where returned | no | ★★★★☆ | not fixture availability |
| Fixture availability report | `/injuries` | where covered | evolving | ★★★★★ | player-fixture, not spell |
| Provider forecast | `/predictions` | snapshot | pre-match | ★★★★★ | assessment, not truth |
| Bookmaker quote | `/odds`, `/odds/live` | retained snapshots | yes | ★★★★★ | quote, not probability/settlement |

## Coverage Procedure

1. Begin with `/leagues` coverage flags for the desired feature.
2. Include an explicit policy for world-scoped competitions, which country-filter discovery can miss.
3. Call the producer and classify outcomes: successful non-empty, successful empty, plan/auth failure, quota failure, or truncation.
4. Record the resulting empirical coverage separately from the advertised flag.
