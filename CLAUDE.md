# Forge Sandbox — Agent Home Base

This repo is Forge's operational home base within the MMRRFinance org.
It is NOT a service repo. It contains no deployable code.

## Purpose

| File / Dir | What it is |
|---|---|
| `coverage-map.json` | Which Lambda handlers have eventable error monitoring coverage |
| `known-errors.json` | Recurring errors Forge has investigated, with RCA and status |
| `runbooks/` | Step-by-step procedures for common Forge tasks |
| `docs/` | Investigation reports, architecture notes, phase summaries |

## How Forge uses this repo

1. **Before starting any error monitoring task** — read `coverage-map.json` to understand current state. Don't re-investigate what's already documented.
2. **After completing a PR** — update `coverage-map.json` to reflect new coverage.
3. **After an RCA** — add an entry to `known-errors.json` with root cause, fix status, and PR link.
4. **When a new pattern emerges** — add a runbook to `runbooks/`.

## Conventions

- All updates to this repo go through PRs. No direct pushes to main.
- Branch naming: `forge/<descriptor>` (same as CoreServices).
- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).
- `coverage-map.json` is the source of truth for monitoring coverage. Keep it current.

## Repo structure

```
forge-sandbox/
├── CLAUDE.md               ← you are here
├── coverage-map.json       ← handler coverage state
├── known-errors.json       ← investigated errors registry
├── runbooks/
│   ├── add-handler-coverage.md
│   ├── investigate-error.md
│   └── update-coverage-map.md
└── docs/
    └── phase-0-summary.md
```

## Current phase

**Phase 0** — Error monitoring coverage baseline.
Goal: get all 21 uncovered Lambda handlers flowing through eventable.
See `docs/phase-0-summary.md` for status.
