# PW-2: Refresh the cached forecast in the background

## Metadata
- **Status:** In Progress
- **Kind:** Feature
- **Priority:** Medium (3)
- **Assignee:** None
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline, iOS
- **Created At:** 2026-09-10 09:00:00
- **Updated At:** 2026-10-14 17:00:00

## Description

**What the user will notice:** Opening the app in the morning shows a forecast from the last hour, even before the network answers.

### Cause

The cache from PW-1 only updates while the app is open, so it is often a day old.

### Fix

Schedule a background refresh every two hours while the app has a saved location. Write the cache atomically.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)
- Blocked by: PW-1

## Documents

- None

## Comments

**2026-10-03** — Started on `sam/pw-2-background-refresh`. Scheduler done; cache write not yet atomic.

**2026-10-14** — Atomic write in. Two refreshes overnight on device, both complete.
