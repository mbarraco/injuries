# Inference Catalog

## Purpose

Separate direct vendor facts from lawful derivations and unsafe claims.

## Overview

Each inference must record input source IDs, query scope, extraction version, execution time, and confidence. An inference does not become a fact merely because it is useful.

## Table of Contents

1. Deterministic derivations
2. Conditional reconstructions
3. Prohibited conclusions

## Deterministic Derivations

| Known evidence | Derive | Confidence | Conditions |
|---|---|---:|---|
| Fixture + home/away teams | fixture participation roles | ★★★★★ | one fixture revision chosen |
| Fixture player performance minutes | player minutes over chosen fixture set | ★★★★★ | deduplicate revisions; define competition scope |
| Player performance goals/assists | player totals over fixture set | ★★★★★ | retain null-vs-zero semantics |
| Fixture events ordered by elapsed time | reported event timeline | ★★★★☆ | preserve equal-time ordering/payload order |
| Lineup selection + substitution events | estimated on-pitch interval | ★★★☆☆ | model abandoned/extra-time cases |
| Fixtures + retained standing snapshots | table evolution at observed times | ★★★★★ | only snapshot timestamps actually stored |
| Transfer date ordering | reported movement chronology | ★★★★☆ | preserve same-date ordering ambiguity |
| Odds values at same snapshot | implied odds-derived metrics | ★★★☆☆ | compatible market/format required |
| Injury record + fixture date | dated availability observation | ★★★★★ | no conversion to spell |
| Sidelined date interval + fixture date | fixture falls within reported period | ★★★☆☆ | date overlap is not missing-fixture proof |

## Conditional Reconstructions

| Evidence | Proposed inference | Confidence | Required label |
|---|---|---:|---|
| Consecutive injury observations, same player/reason | possible absence spell | ★★☆☆☆ | `inferred_spell`, gap rule, reason rule |
| Transfer to team then next transfer | likely membership interval | ★★☆☆☆ | `inferred_membership`; exclude loan/unknown caveats |
| Squad snapshots at two dates | membership observed in interval bounds | ★★★☆☆ | lower/upper observation bounds, not effective dates |
| Fixture lineup + no player statistic | selected but no observed performance row | ★★★☆☆ | not “did not play” |
| Player fixture performances for a team | evidenced playing association | ★★★★★ | role/date/competition scoped |
| Final fixtures + rules engine | recalculated standings | ★★★☆☆ | explicit tie-break rules and complete result set |
| Prediction snapshot + final result | prediction calibration outcome | ★★★★★ | prediction timestamp before kickoff |
| Odds snapshot + final result | retrospective market outcome | ★★★★★ | selection/settlement rules explicit |

## Prohibited Conclusions

- Do not infer a medical diagnosis, severity, recovery date, or injury spell ID from `/injuries`.
- Do not infer that a player was registered, contracted, or played from a transfer alone.
- Do not infer that a bench player appeared from a lineup.
- Do not infer missing data means a player/event/injury did not exist.
- Do not infer a league-season’s feature coverage from country membership or another competition.
- Do not treat a current standing as the table at a historical fixture date.
- Do not treat an odds quote or prediction as an outcome probability without explicit model assumptions.

## Inference Record

Store: `inference_id`, type, input entity keys, source response hashes, code version, parameters (such as allowed fixture gap), produced time, confidence, and invalidation conditions. Recompute when upstream revisions change.
