# PW-6: Keep the cache under 5 MB per location

## Metadata
- **Status:** Done
- **Kind:** Task
- **Priority:** Medium (3)
- **Assignee:** None
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline, Performance
- **Created At:** 2026-09-08 09:00:00
- **Updated At:** 2026-09-20 17:00:00

## Description

**What the user will notice:** Nothing visible; the app's storage stays small with many saved places.

### Cause

Full responses include 14 days of hourly data and radar thumbnails.

### Fix

Store 3 days hourly and 10 days daily; drop radar thumbnails from the cache.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)

## Documents

- None

## Comments

**2026-09-20** — Done. 20 saved places use 31 MB, down from 140 MB.
