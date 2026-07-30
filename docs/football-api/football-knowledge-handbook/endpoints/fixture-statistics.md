# Fixture Statistics Knowledge Domain

## Purpose

Measure team-level match statistics and, where requested, period-level context.

## Overview

`/fixtures/statistics` produces a fixture × team measurement set. Statistic names and values are provider vocabulary; they are not universally comparable across competitions without metadata.

## Table of Contents

1. Knowledge and grain
2. Authority and limits
3. Engineering mapping

## Knowledge Produced

Possession, shots, fouls, passes, corners, offsides, cards, and other returned named team statistics, potentially constrained by half.

## Primary and Secondary Entities

Primary: `FixtureTeamStatistic`; secondary: `Fixture`, `Team`, `StatisticType`, optional `MatchPeriod`.

## Relationships, Grain, and Keys

One value per fixture × team × statistic type × period × response revision. Natural key must include statistic label and period; do not pivot permanently into a fragile wide table.

## Temporal Semantics and Authority

Live/snapshot then settled. Authoritative for provider measurement at retrieval; not for event-level provenance or a universal measurement definition.

## Facts Learned and Missing

Learns aggregate team match context. Does not learn player contribution, definitive tactical setup, tracking data, or cause of a statistic.

## Join, Download, Freshness, and History

Fetch by fixture after fixture spine; lower priority than player performance for player-rate analysis. Poll live/settle and retain revisions. Join fixture/team/period dimensions.

## Confidence

★★★★☆ returned metric under stated provider label; ★★☆☆☆ cross-provider or cross-era comparability.

## Graph and Warehouse Mapping

Long `fixture_team_statistic` fact plus `statistic_type` dimension; graph reifies measurement node with `MEASURED_FOR` and `IN_FIXTURE`.

## Inference, Redundancy, and Engineering Notes

Can create contextual features for outcomes, not causal explanations. `/teams/statistics` overlaps at season aggregate grain and must never be joined as though it were fixture-level data.
