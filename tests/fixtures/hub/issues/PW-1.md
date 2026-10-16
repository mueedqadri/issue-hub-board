# PW-1: Show the last forecast when the phone is offline

## Metadata
- **Status:** Done
- **Kind:** Feature
- **Priority:** High (2)
- **Assignee:** None
- **Estimate:** Small
- **Due Date:** N/A
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline

## Description

**What the user will notice:** With no signal, the app opens on the last
forecast it saw, marked "Updated 3 h ago", instead of a blank screen.

### Cause

`ForecastStore.load()` throws on a network error and the view shows its empty
state. The last response is never kept.

### Fix

Keep the last successful response on disk, keyed by location. Serve it when
the network fails, with its fetch time.

### Acceptance

- `ForecastStoreTests.testServesCachedForecastOffline` fails on `main` and passes after.
- Airplane mode on a device: the app opens on the cached forecast.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)
- Blocks: [PW-2](./PW-2.md)

## Comments

- 3f9c2a1 PW-1: Show the last forecast when the phone is offline

**2026-10-02** — Merged into `offline-forecasts`. Unit suite 214 passed,
0 failed. Checked on device in airplane mode: cached forecast, "Updated 3 h ago".
