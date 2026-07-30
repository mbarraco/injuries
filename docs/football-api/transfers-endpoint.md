# Knowledge Domain: Player Transfers

**Primary Endpoint**

GET /transfers

---

# Overview

The Transfers endpoint represents the movement of professional football players
between clubs over time.

Unlike most football endpoints, which describe events occurring during matches,
this endpoint describes **career evolution**.

Transfers create the temporal relationship between a player and the clubs they
represent and are therefore one of the primary sources for reconstructing
historical squad composition.

This endpoint should be considered the authoritative source for player movement.

---

# Knowledge Produced

This endpoint creates knowledge about four primary entities.

Player

Transfer

Team

Career

It also creates temporal relationships between those entities.

---

# Grain

One record represents

Player
    transferred
        from Team A
        to Team B
            on Date

If a player has transferred 12 times during their career, the endpoint should
produce 12 transfer records.

---

# Entity Model

Player
    id
    name

Transfer
    date
    type
    teams

Team
    id
    name
    logo

---

# Relationships Created

Player

TRANSFERRED_FROM

Team


Player

TRANSFERRED_TO

Team


Transfer

HAS_SOURCE_TEAM

Team


Transfer

HAS_DESTINATION_TEAM

Team


Transfer

INVOLVES

Player

---

# Semantic Graph

Player
        │
        │ transferred
        ▼
Transfer
    │               │
    │ from          │ to
    ▼               ▼
Team A          Team B

---

# Facts Learned

From every transfer the agent learns

• Player changed club

• Previous club

• Destination club

• Date of transfer

• Transfer category

• Both clubs involved

This endpoint does NOT indicate whether the player actually appeared for either
club.

Playing time must be reconstructed from fixture data.

---

# Entity Reference

## Player

Primary Key

player.id

Stable

Yes

Description

Unique football player.

Authority

Player endpoint.

Transfer endpoint references existing players.

---

## Team

Primary Key

team.id

Stable

Yes

Description

Professional club or national team.

Authority

Teams endpoint.

---

## Transfer

Transfer has no globally stable identifier.

Instead, a transfer should be modeled as

(player_id,
from_team_id,
to_team_id,
transfer_date)

or

(player_id,
transfer_date,
destination_team_id)

depending on implementation.

---

# Attributes

## Player

| Attribute | Description | Stability |
|------------|-------------|-----------|
| id | Stable player identifier | High |
| name | Display name | Medium |

---

## Teams

### Outgoing

Represents the player's previous club.

Contains

id

name

logo

---

### Incoming

Represents the destination club.

Contains

id

name

logo

---

## Transfer

### Date

Date the transfer became effective.

Temporal.

---

### Type

Human-readable transfer classification.

Examples

Transfer

Loan

Free

Unknown

The API may introduce additional values.

Consumers should not hard-code enumerations.

---

# Temporal Semantics

Transfers represent

Player membership

over time.

This endpoint is one of the few sources that allows reconstruction of a player's
career chronology.

Timeline

Club A

↓

Club B

↓

Club C

↓

Club D

---

# Historical Coverage

Expected

Historical

Yes

Future

No

Live

No

Transfers appear after they are officially recorded.

---

# Freshness

Recommended synchronization

Daily during transfer windows.

Weekly outside transfer windows.

---

# Authority

Authoritative for

✓ Club movement

✓ Destination club

✓ Previous club

✓ Transfer date

Not authoritative for

✗ Squad membership

✗ Playing time

✗ Contracts

✗ Salaries

✗ Registration status

---

# Inference Opportunities

The following facts may be inferred.

## Career Timeline

Transfers ordered chronologically reconstruct

Player Career.

---

## Club Membership

Between two consecutive transfers

the player can be assumed to belong to the destination club.

---

## Historical Squad

Combining

Transfers

+

Fixtures

allows reconstruction of club rosters for arbitrary dates.

---

## Team Evolution

Aggregating transfers reveals

• rebuilding periods

• selling clubs

• buying clubs

• academy promotion patterns

---

## Transfer Network

Graph

Club

↓

Player

↓

Club

↓

Player

↓

Club

Allows

network analysis

community detection

market flow

club connectivity

---

# Relationships with Other Endpoints

## Players

Provides

identity

height

weight

birth

nationality

Transfers reference existing players.

---

## Teams

Provides

club metadata

stadium

country

logos

Transfers only reference clubs.

---

## Fixtures

Determines

whether a transferred player actually appeared for the destination club.

---

## Squads

Current roster.

Transfers explain

how that roster was formed.

---

## Injuries

Useful for determining whether a transfer occurred while injured.

---

## Trophies

Allows attribution of trophies to clubs that the player represented.

---

# Data Warehouse

Suggested Fact Table

fact_transfers

Columns

player_id

from_team_id

to_team_id

transfer_date

transfer_type

loaded_at

Indexes

player_id

transfer_date

to_team_id

---

# Knowledge Graph

(:Player)

-[:TRANSFERRED]->

(:Transfer)

-[:FROM]->

(:Team)



(:Transfer)

-[:TO]->

(:Team)

---

# Agent Notes

Use this endpoint to answer

Where did this player come from?

Which club signed this player?

When did the move occur?

Which clubs have exchanged the most players?

What club did the player belong to on date X?

Do not use this endpoint to determine

whether the player actually played,

started,

or remained registered after the transfer.

Those require Fixture, Squad and Player endpoints.

---

# Crawl Strategy

Historical

For every player

download complete transfer history.

Incremental

Refresh active players daily.

Increase frequency during transfer windows.

---

# Confidence

Player identity

★★★★★

Transfer date

★★★★★

Destination club

★★★★★

Source club

★★★★★

Transfer type

★★★★☆

Contract details

☆☆☆☆☆

Salary

☆☆☆☆☆

Medical examination

☆☆☆☆☆

Registration status

☆☆☆☆☆

---

# Summary

This endpoint is the foundation of the player career graph.

It answers **where a player moved**, **when**, and **between which clubs**, but
must be combined with Fixtures, Squads, and Player profiles to reconstruct a
complete sporting career.