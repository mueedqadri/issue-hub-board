# PW-2: Refresh the cached forecast in the background

## Metadata
- **Status:** In Progress
- **Kind:** Feature
- **Priority:** Medium (3)
- **Assignee:** None
- **Estimate:** Small
- **Due Date:** N/A
- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)
- **Labels:** Offline, iOS

## Description

**What the user will notice:** Opening the app in the morning shows a forecast
from the last hour, even before the network answers.

### Fix

Schedule a background refresh every two hours while the app has a saved
location. Reuse the PW-1 cache; never write a partial response.

### Acceptance

- A unit test drives the scheduler with a fake clock and sees one refresh per window.
- The cache file is never half-written (atomic replace).

## Relationships

- Project: [Offline Forecasts](../projects/offline-forecasts.md)
- Blocked by: [PW-1](./PW-1.md)

## Comments

**2026-10-03** — Started on `sam/pw-2-background-refresh`. Scheduler done;
cache write not yet atomic.
