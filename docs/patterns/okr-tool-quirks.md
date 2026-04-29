# OKR Tool Quirks — Known API Gotchas

**Type:** Reference / Gotcha Catalog  
**Category:** OKR Tooling / Agent Operational Patterns  
**Status:** Canonical — consult before writing any OKR tool call

---

## Overview

Five confirmed quirks in the OKR entity API that cause silent failures or confusing errors. Each entry includes the symptom, the correct workaround, and a canonical example from a real Forge session.

---

## Quirk 1: `list_entities` Filtered Calls Throw MCP -32603

**Type:** Bug / API Limitation  
**Severity:** High — causes complete call failure with no data returned

### Symptom

Calling `list_entities` with any filter beyond `entityType` throws an MCP protocol error:

```
MCP error -32603: Internal error
```

The call returns nothing. No partial results, no fallback. The error is opaque and does not indicate which filter caused the failure.

### Correct Workaround

Use `list_entities` with **only** `entityType` (and optionally `limit`) to retrieve the full unfiltered set, then filter client-side in Python:

```python
import json

with open('/tmp/spill-output.json') as f:
    data = json.load(f)

items = data.get('items', [])
# Filter client-side
matching = [i for i in items if i.get('ownerId') == 'agent:forge']
```

### Canonical Example

During a KR progress audit session (2026-04-29), the following call failed with -32603:

```json
// BROKEN — throws MCP -32603
list_entities({
  "entityType": "WorkItem",
  "ownerId": "agent:forge",
  "status": "active"
})
```

Replaced with:

```json
// WORKS — unfiltered list, then python3 parse
list_entities({
  "entityType": "WorkItem",
  "limit": 100
})
// → spill file written to /tmp/...
// → python3 script filters for ownerId == "agent:forge" and status == "active"
```

---

## Quirk 2: `search_entities` Returns `hits.items`, Not `items`

**Type:** Schema Mismatch / Footgun  
**Severity:** High — naive access returns `None`/`undefined` silently

### Symptom

After a successful `search_entities` call, accessing `data["items"]` returns `None` or an empty result even when matches exist. The call itself succeeds (no error), making this hard to debug.

### Correct Workaround

Navigate the nested response structure: `data["hits"]["items"]`. Always use this path when consuming `search_entities` output:

```python
import json

with open('/tmp/spill-output.json') as f:
    data = json.load(f)

# WRONG — returns None
items = data.get('items', [])

# CORRECT — returns actual results
items = data.get('hits', {}).get('items', [])
```

### Canonical Example

During a WorkItem lookup session, a `search_entities` call for `entityType=WorkItem, query="KR1"` returned a spill file. Accessing `data["items"]` yielded `[]`. Switching to `data["hits"]["items"]` returned 4 matching WorkItems.

```python
# Correct access pattern for search_entities output
with open(spill_path) as f:
    data = json.load(f)

results = data.get('hits', {}).get('items', [])
print(f"Found {len(results)} results")
for r in results:
    print(r['id'], r.get('title', ''))
```

---

## Quirk 3: WorkItem IDs from Prompt/List May Be Partial UUIDs

**Type:** Data Integrity / Silent Failure  
**Severity:** High — `get_entity` with a wrong ID returns 404 or wrong entity

### Symptom

A WorkItem ID copied from a prompt, a list response, or memory context may be truncated or padded incorrectly. Calling `get_entity` with a guessed or manually-padded UUID either returns 404 or — worse — resolves to a completely different entity.

### Correct Workaround

**Never call `get_entity` with an ID that was not returned verbatim by a prior API call in the same session.** If you have a partial or uncertain ID, resolve it first via `search_entities` using the title or description as the query, then use the `id` field from the returned hit:

```python
# Step 1: resolve via search
search_entities({
  "query": "KR1: Write OKR tool quirks doc",
  "entityTypes": ["WorkItem"]
})

# Step 2: extract the canonical ID from hits.items[0].id
# Step 3: THEN call get_entity with that verified ID
get_entity({ "entityType": "WorkItem", "id": "<verified-id-from-step-2>" })
```

### Canonical Example

In a planning session, the prompt contained `workItemId: 09a4c01b` (8 chars). The full UUID is `09a4c01b-a9ef-459c-8e6d-f0611992f000`. Calling `get_entity` with only `09a4c01b` would fail. The correct approach: the full UUID was provided in the prompt context — always use the complete value. When only a partial is available, use `search_entities` to resolve the canonical full ID before any `get_entity` call.

---

## Quirk 4: Spill Files Re-Spill When Read with `readFile` — Use Python3 Parser

**Type:** Tool Interaction Bug  
**Severity:** Medium — creates infinite spill loop, data never accessible via `readFile`

### Symptom

When an API response is too large, the tool writes it to a spill file at `/tmp/<uuid>.json` and returns the path. Calling `readFile` on that spill path causes the tool to re-spill the content to a *new* spill file, returning another path. This loop repeats indefinitely — the data is never returned as readable text.

### Correct Workaround

Write a Python3 script to `/tmp/parse-spill.py`, execute it with `bash`, and read its stdout. The script opens the spill file directly via the filesystem and extracts only the fields needed:

```python
# /tmp/parse-spill.py
import json, sys

spill_path = sys.argv[1]
with open(spill_path) as f:
    data = json.load(f)

# For list_entities output:
items = data.get('items', [])
# For search_entities output:
# items = data.get('hits', {}).get('items', [])

for item in items:
    print(json.dumps({
        'id': item.get('id'),
        'title': item.get('title'),
        'status': item.get('status'),
    }))
```

Then invoke:

```bash
python3 /tmp/parse-spill.py /tmp/<spill-uuid>.json
```

### Canonical Example

During a bulk WorkItem audit, `list_entities({ "entityType": "WorkItem", "limit": 100 })` returned:

```
Response too large. Written to /tmp/a3f9c821-list-entities.json
```

Calling `readFile("/tmp/a3f9c821-list-entities.json")` returned:

```
Response too large. Written to /tmp/b7d2e044-readfile.json
```

The fix: write `/tmp/parse-spill.py` with the script above, run `python3 /tmp/parse-spill.py /tmp/a3f9c821-list-entities.json`, and parse stdout directly.

---

## Quirk 5: `search_entities` with `ownerId` Works; `list_entities` with `ownerId` Does Not

**Type:** API Inconsistency  
**Severity:** Medium — causes -32603 error (see Quirk 1) when using the wrong tool

### Symptom

`list_entities` with an `ownerId` filter throws MCP -32603 (same as all filtered `list_entities` calls — see Quirk 1). However, `search_entities` with an `ownerId` filter works correctly and returns matching entities.

This asymmetry is counterintuitive: `list_entities` looks like the natural choice for "give me all WorkItems owned by X," but it fails. `search_entities` is the correct tool for owner-filtered queries.

### Correct Workaround

Use `search_entities` (not `list_entities`) for any query that filters by `ownerId`:

```json
// BROKEN — throws MCP -32603
list_entities({
  "entityType": "WorkItem",
  "ownerId": "agent:forge"
})

// WORKS — use search_entities instead
search_entities({
  "entityTypes": ["WorkItem"],
  "ownerId": "agent:forge"
})
```

Then access results via `hits.items` (see Quirk 2).

### Canonical Example

During a daily work-planning session, the agent needed all active WorkItems owned by `agent:forge`. The first attempt used `list_entities` with `ownerId` and received MCP -32603. Switching to `search_entities` with the same `ownerId` filter returned 7 matching WorkItems correctly via `data["hits"]["items"]`.

```json
// Final working call
search_entities({
  "entityTypes": ["WorkItem"],
  "ownerId": "agent:forge",
  "status": ["active"]
})
// Access: response["hits"]["items"]
```

---

## Quick Reference

| # | Quirk | Broken Call | Working Alternative |
|---|-------|-------------|---------------------|
| 1 | `list_entities` filtered → MCP -32603 | `list_entities({ ownerId: "x" })` | Unfiltered list + python3 client-side filter |
| 2 | `search_entities` response path | `data["items"]` | `data["hits"]["items"]` |
| 3 | Partial UUID in prompt/list | `get_entity({ id: "09a4c01b" })` | `search_entities` to resolve full ID first |
| 4 | Spill file re-spills on `readFile` | `readFile("/tmp/spill.json")` | `python3 /tmp/parse-spill.py /tmp/spill.json` |
| 5 | `list_entities` with `ownerId` → -32603 | `list_entities({ ownerId: "x" })` | `search_entities({ ownerId: "x" })` |

---

## Related Patterns

- [`handle-lambda-wrapper.md`](./handle-lambda-wrapper.md) — unrelated but canonical pattern doc format reference
- [`captureError-rethrow.md`](./captureError-rethrow.md) — unrelated but canonical pattern doc format reference
