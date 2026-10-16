# Project: Radar Rewrite

## Metadata
- **Status:** In Progress
- **Lead:** Priya
- **Members:** None
- **Start Date:** 2026-09-15
- **Target Date:** 2026-12-01

## Documents
- Illustrated plan: [`radar-rewrite.html`](./radar-rewrite.html)

## Description

The radar is the most used screen and the slowest. This project moves tile drawing to the GPU, then builds the smooth rain loop and the next-hour arrows on top of it.

## Shared contract

| Question | Answer |
| --- | --- |
| How is each issue judged done? | By its "What the user will notice", seen on a device. |
| How is it checked? | The unit suite, plus a device run for anything on screen. |
| Order? | One issue at a time, each reviewed before the next. |

## Issues

- [PW-4](../issues/PW-4.md) - Stop the radar map from flickering on rotate
- [PW-10](../issues/PW-10.md) - Draw radar tiles on the GPU
- [PW-11](../issues/PW-11.md) - Animate the last two hours of rain
- [PW-12](../issues/PW-12.md) - Show where rain is heading in the next hour
- [PW-13](../issues/PW-13.md) - Pick radar colors that work for color-blind people
- [PW-14](../issues/PW-14.md) - Remember the radar's zoom and position
- [PW-15](../issues/PW-15.md) - Radar crashes when the tile server returns an empty image
- [PW-16](../issues/PW-16.md) - Cache radar tiles for an hour
