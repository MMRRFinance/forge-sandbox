# Runbook: Update coverage-map.json After a PR Merges

Run this after a CoreServices PR that adds error monitoring coverage is merged.

## Steps

1. Open `coverage-map.json`
2. Find the handler entry by `functionName` or `file`
3. Update:
   - `covered`: `true`
   - `coverageMethod`: `"handleLambda"` or `"captureError + re-throw"`
   - `prStatus`: `"merged"`
4. Update `_meta`:
   - Increment `coveredCount`
   - Decrement `uncoveredCount`
   - Update `lastUpdated` to today's date
   - Update `updatedBy` to `"Forge (post-merge update)"`
5. Commit: `chore: update coverage-map after PR #NNN merged`
6. Open PR to forge-sandbox main

## Coverage percentage formula

```
coverage% = coveredCount / totalHandlers * 100
```

Target: 100% (all 21 handlers covered).
Current baseline (Phase 0 start): 0/21 = 0%.
After Phase 0 PRs merge: 3/21 = 14.3%.
