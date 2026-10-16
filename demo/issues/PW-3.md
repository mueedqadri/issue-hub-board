# PW-3: Say how old an offline forecast is in words

## Metadata
- **Status:** In Review
- **Kind:** Improvement
- **Priority:** Medium (3)
- **Assignee:** None
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline, Copy
- **Created At:** 2026-09-10 09:00:00
- **Updated At:** 2026-10-15 17:00:00

## Description

**What the user will notice:** An offline forecast says "Updated 2 hours ago" in plain words under the temperature.

### Cause

The cached forecast looked live, so people trusted a stale one.

### Fix

Show a relative age line when the forecast is older than 15 minutes, and "No connection" beside it when offline.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)
- Blocked by: PW-1
- Related: PW-21

## Documents

- None

## Comments

**2026-10-15** — In review. Copy checked with VoiceOver; reads as one phrase.
