# PW-7: Show offline mode in the Apple Watch app

## Metadata
- **Status:** Backlog
- **Kind:** Feature
- **Priority:** Medium (3)
- **Assignee:** None
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline, watchOS
- **Created At:** 2026-09-22 09:00:00
- **Updated At:** 2026-09-22 17:00:00

## Description

**What the user will notice:** The watch shows the phone's last forecast when neither has signal.

### Cause

The watch app asks the network directly and gives up.

### Fix

Sync the cached forecast to the watch with the existing complication update.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)
- Blocked by: PW-2

## Documents

- None

## Comments
