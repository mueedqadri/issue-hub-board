# Pocket Weather hub rules

House rules for this hub, on top of the issue-hub skill. Agents read this file
before filing or changing issues.

## Kinds and labels

The lists live in `hub.json`. Every issue gets one Kind and at least one area
label. Add `iOS` or `watchOS` only when the issue is about that platform.

## Commits and branches

- Commit subject: `PW-<n>: <imperative summary>`, at most 72 characters.
- Branch: `sam/pw-<n>-<slug>`.

## Things never to do

- Never commit the forecast provider's API key; it lives in the app's
  `Secrets.xcconfig`, which is gitignored.
