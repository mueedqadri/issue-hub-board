# PW-4: Stop the radar map from flickering on rotate

## Metadata
- **Status:** Todo
- **Kind:** Bug
- **Priority:** High (2)
- **Assignee:** None
- **Project:** [Radar Rewrite](../projects/radar-rewrite.md)
- **Labels:** Radar, iOS
- **Created At:** 2026-09-20 09:00:00
- **Updated At:** 2026-10-10 17:00:00

## Description

**What the user will notice:** Rotating the phone keeps the radar layer steady instead of flashing white for a frame.

### Cause

The tile layer is torn down and rebuilt on every size change.

### Fix

Keep the layer and only update its frame; reload tiles when the zoom level actually changes.

### Acceptance

- Seen working on a device, as described above.
- A test that fails before the change and passes after.

## Relationships

- Project: [Radar Rewrite](../projects/radar-rewrite.md)
- Related: PW-14

## Documents

- None

## Comments
