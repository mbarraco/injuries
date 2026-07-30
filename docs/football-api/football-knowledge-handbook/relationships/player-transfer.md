# Player–Transfer–Team Relationship

## Purpose
Represent player movement with parties and date without overstating membership.

## Overview
Transfers must be reified because source team, destination team, date, type, and provenance belong to the relationship.

## Table of Contents
1. Meaning 2. Evidence 3. Model

## Semantics and Evidence
`/transfers` produces `Transfer OF_PLAYER Player`, `FROM Team`, and `TO Team`.

## Cardinality, History, and Mapping
One player has many transfers; a team participates in many transfers. `fact_transfer` has player/source/destination/date/type; Neo4j uses a `Transfer` node. No global transfer ID: retain raw hash/collision policy.
