---
name: Bug report
about: Something behaves differently from what the README or docs describe
title: ""
labels: bug
---

## What happened

<!-- The observable result: status code, action (day/review/ask), resolved food_id. -->

## What you expected

<!-- Quote the claim you are relying on, with the file or document it comes from. -->

## How to reproduce

```sh
# A request or command someone else can run. Include the locale and sample_id.
```

## Environment

<!-- OS, Node version, Python version, and whether the Turkish catalogue was
     installed with `make pack` (a `503` for `locale: "tr"` is expected without it). -->

## Accuracy reports

If the problem is a wrong answer rather than a crash, say which evaluation set
you saw it on. The scorecard in [docs/evaluation.md](../../blob/main/docs/evaluation.md)
states what the fixtures do and do not prove.
