# Pocket Weather: state of the project

One page. Read it in five minutes, then act. Every section says the date it
was last checked against the code; when the facts move, the date moves.

**Last verified: 2026-10-03.**

## 1. Branches: where the work lives

| Branch | vs `main` | Issues | Pushed? |
| --- | --- | --- | --- |
| `main` | the mainline | PW-1 | Yes |
| `offline-forecasts` | +4 | PW-1, PW-2 (in progress) | Yes |

## 2. Bodies of work

What is in flight, one line each, with its project page.

- [Offline Forecasts](./projects/offline-forecasts.md): PW-1 done, PW-2 in progress, PW-3 next.

## 3. Gates

What must be true before the next release or merge.

- `offline-forecasts` merges to `main` only after PW-2's atomic cache write lands.

## 4. Next five actions

1. Finish PW-2's atomic cache write.
2. Review PW-2 on a device.
3. Start PW-3.
4. Fix PW-4 (radar flicker).
5. Merge `offline-forecasts`.

## 5. Parked on purpose

What we decided not to do, and why, so nobody re-opens it by accident.

- UV index (PW-5): provider data is incomplete.
