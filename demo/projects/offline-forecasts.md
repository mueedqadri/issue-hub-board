# Project: Offline Forecasts

## Metadata
- **Status:** In Progress
- **Lead:** Sam
- **Members:** None
- **Start Date:** 2026-09-02
- **Target Date:** 2026-11-01

## Documents
- Illustrated plan: [`offline-forecasts.html`](./offline-forecasts.html)
- Field notes: [Offline usage interviews](../documents/offline-usage-interviews.md)

## Description

Hikers open the app where there is no signal and get a blank screen. The forecast they saw an hour ago would be enough. This project keeps the last forecast, keeps it fresh, and says how old it is.

## Shared contract

| Question | Answer |
| --- | --- |
| How is each issue judged done? | By its "What the user will notice", seen on a device. |
| How is it checked? | The unit suite, plus a device run for anything on screen. |
| Order? | One issue at a time, each reviewed before the next. |

## Issues

- [PW-1](../issues/PW-1.md) - Show the last forecast when the phone is offline
- [PW-2](../issues/PW-2.md) - Refresh the cached forecast in the background
- [PW-3](../issues/PW-3.md) - Say how old an offline forecast is in words
- [PW-6](../issues/PW-6.md) - Keep the cache under 5 MB per location
- [PW-7](../issues/PW-7.md) - Show offline mode in the Apple Watch app
- [PW-8](../issues/PW-8.md) - Prefetch forecasts for places on a planned route
