# PW-8: Prefetch forecasts for places on a planned route

## Metadata
- **Status:** Backlog
- **Kind:** Feature
- **Priority:** Low (4)
- **Assignee:** None
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline
- **Created At:** 2026-09-25 09:00:00
- **Updated At:** 2026-09-25 17:00:00

## Description

**What the user will notice:** Before a trip, the app saves the forecast for each stop so it is there without signal.

### Cause

Only saved locations are cached.

### Fix

Add "Save for offline" to a route shared from Maps; cache each waypoint like a saved location.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)

## Documents

- None

## Comments
