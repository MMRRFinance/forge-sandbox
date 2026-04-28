# OKR Tooling API Quirks

**Purpose:** Document confirmed API quirks in the OKR tool layer that cause re-discovery waste across sessions. Every quirk here was hit at least once in production use. Read this before starting any OKR-heavy session.

---

## Quirk 1: `search_entities` returns `hits.items`, not `items`

**Symptom:**  
Parsing `data['items']` returns an empty list even when `total > 0`. The data is present but silently unreachable.

**Correct workaround:**  
Always parse `data['hits']['items']` for the result array and `data['hits']['total']` for the count. Never assume a top-level `items` key.

```python
# WRONG — returns []
results = data['items']

# CORRECT
results = data['hits']['items']
total   = data['hits']['total']
```

**Canonical example session:** 2026-04-24 and 2026-04-27 OKR sessions (both hit this on first query).

---

## Quirk 2: `list_entities` with `category` filter throws MCP error -32603

**Symptom:**  
Calling `list_entities(entityType='Objective', category='personal')` (or any category value) raises MCP error `-32603`. The filter is silently unsupported on `list_entities`.

**Correct workaround:**  
Use `search_entities` instead, passing `category` as an **array**:

```python
# WRONG — MCP -32603
list_entities(entityType='Objective', category='personal')

# CORRECT
search_entities(entityTypes=['Objective'], category=['personal'])
```

Note: `search_entities` accepts `category` as an array; `list_entities` does not support it at all.

**Canonical example session:** 2026-04-27 session, step 1.

---

## Quirk 3: Large results spill to disk — requires `bash` + `python3` to parse

**Symptom:**  
Tool returns `"Large result spilled to /tmp/agent-spill/<uuid>.json"` instead of inline data. Attempting to use the result directly fails.

**Correct workaround:**  
Read the spill file via `bash` and pipe through `python3` using the `hits.items` pattern (see Quirk 1):

```bash
cat /tmp/agent-spill/<uuid>.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data['hits']['items']
total = data['hits']['total']
for item in items:
    print(item['id'], item.get('title', item.get('statement', '')))
"
```

Key points:
- The spill file is valid JSON — same schema as inline results.
- Always apply the `hits.items` path (Quirk 1) when parsing spill files.
- Spills occur on any query returning more than ~20 results.

**Canonical example session:** Every OKR session with >20 results (consistent across Apr 2026 sessions).

---

## Quirk 4: WorkItem IDs from list output may fail `get_entity` lookup

**Symptom:**  
`get_entity(entityType='WorkItem', id='<id-from-list>')` returns `null` even though the ID appeared in a prior `list_entities` or `search_entities` result. Likely caused by character substitution or rendering artifacts in tool output.

**Correct workaround:**  
If `get_entity` returns null for a WorkItem ID, re-fetch via `list_entities` or `search_entities` filtered by `objectiveId`, then scan the result for the target item by title or other known field:

```python
# WRONG — may return null due to ID corruption
get_entity(entityType='WorkItem', id='cb5497df-...')

# CORRECT — re-fetch via parent objective filter
search_entities(entityTypes=['WorkItem'], objectiveId='<parent-objective-id>')
# then scan results for the item you need
```

As a secondary fallback, filter by `keyResultId` if the objectiveId is not known.

**Canonical example session:** 2026-04-27 session (WorkItem ID `cb5497df-...` returned null on direct lookup).

---

## Quirk 5: KeyResult `status` valid values differ from WorkItem and Objective

**Symptom:**  
`create_entity(entityType='KeyResult', status='active')` raises MCP error `"Invalid status"`. The status enum for KeyResults is a completely different set from WorkItems and Objectives.

**Correct workaround:**  
Use the correct enum per entity type:

| Entity type | Valid `status` values |
|---|---|
| **KeyResult** | `not-started` · `on-track` · `at-risk` · `off-track` · `completed` · `missed` |
| **WorkItem** | `active` · `completed` · `blocked` · `draft` |
| **Objective** | `draft` · `active` · `completed` · `archived` · `at-risk` |
| **Hypothesis** | `draft` · `active` · `completed` · `archived` · `at-risk` |

Never use `active`, `draft`, or `archived` for a KeyResult. Never use `on-track` or `off-track` for a WorkItem.

**Canonical example session:** 2026-04-27 session, KR creation attempt.

---

## Quick-reference cheat sheet

| Situation | Do this |
|---|---|
| Querying any entity list | Use `search_entities`, not `list_entities` |
| Filtering by `category` | Pass as array: `category=['personal']` |
| Parsing any result | Always use `data['hits']['items']` |
| Result spilled to disk | `cat <file> \| python3 -c "...data['hits']['items']..."` |
| WorkItem lookup returns null | Re-fetch via `objectiveId` filter in `search_entities` |
| Setting KR status | Use `not-started/on-track/at-risk/off-track/completed/missed` |

---

*Last updated: 2026-04-28 — WI 28dd73f8*
