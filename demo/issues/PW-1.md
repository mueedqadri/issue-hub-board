# PW-1: Show the last forecast when the phone is offline

## Metadata
- **Status:** Done
- **Kind:** Feature
- **Priority:** High (2)
- **Assignee:** None
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline, Forecast
- **Created At:** 2026-09-02 09:00:00
- **Updated At:** 2026-09-12 17:00:00

## Description

**What the user will notice:** With no signal, the app shows the forecast it last loaded instead of a blank screen.

### Cause

Every launch fetched the forecast and showed nothing until it arrived. Hikers open the app exactly where there is no signal.

### Fix

Cache the last full forecast response per saved location and render it first. Replace it only with a complete newer response.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)
- Blocks: PW-2, PW-3

## Documents

- None

## Comments

**2026-09-12** — Merged `a91c2e0`. Airplane mode on an iPhone 15 shows yesterday's forecast in 0.3 s.
