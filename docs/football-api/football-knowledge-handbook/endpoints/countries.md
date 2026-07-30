# Countries and Timezones Knowledge Domain

## Purpose

Supply controlled reference values used to discover league coverage and form valid time-scoped queries.

## Overview

`/countries` produces the API’s supported country labels; `/timezones` produces accepted timezone identifiers. Neither establishes citizenship, governing-body membership, or a venue’s legal jurisdiction.

## Table of Contents

1. Knowledge and grain
2. Authority and time
3. Engineering mapping

## Knowledge Produced

Vendor-supported country and timezone reference values, including country code/flag metadata where returned.

## Primary and Secondary Entities

`CountryReference`, `TimezoneReference`; league and team country strings are secondary join candidates.

## Relationships, Grain, and Keys

One row per returned reference value. Use provider country code when returned; otherwise retain normalized label plus raw label. Timezone key is its canonical IANA-like returned string.

## Temporal Semantics and Authority

Slowly changing reference snapshot. Authoritative for accepted API values, not for football geography or historical nationality.

## Facts Learned and Missing

Learns what the provider recognizes. Does not enumerate leagues, teams, fixtures, or country membership for a player.

## Join, Download, Freshness, and History

Join country labels cautiously to league/team profiles; store raw and canonical forms. Cold-start and refresh infrequently; retain revisions because labels can change.

## Confidence

★★★★☆ for provider vocabulary; ★★☆☆☆ for semantic country reconciliation without a code.

## Graph and Warehouse Mapping

`CountryReference` and `TimezoneReference` dimensions; edges to entities are source-qualified, not universal ontology facts.

## Inference, Redundancy, and Engineering Notes

Useful for discovery validation and query normalization. `/teams/countries` overlaps only in endpoint capability, not country semantics. Index canonical code/label and preserve the source response.
