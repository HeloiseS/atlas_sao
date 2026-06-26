# atlasapiclient reference (for ATLAS SAO follow-up project)

Source: `~/software/atlasapiclient/atlasapiclient/` (client.py, authentication.py, config.py, utils.py, exceptions.py). Read-only audit, no code changed. Written for someone who already knows `mookodiListWizard.py`.

## 1. Structure & auth flow

- `APIClient` (client.py:45) — abstract base. All request classes subclass it.
  - `__init__(api_config_file=None, auto_refresh_fl=True)`: loads `ATLASConfigFile` (config.py:7), wraps the token string in `Token` (authentication.py:23), validates/normalizes `base_url` via `validate_url` (utils.py:36).
  - Default config path if `api_config_file=None`: `atlasapiclient/config_files/api_config_MINE.yaml` (utils.py:11, `API_CONFIG_FILE`).
  - `.headers` property builds `{'Authorization': 'Token <val>'}` fresh on every access (client.py:106-108) — always current even after a refresh.
  - `get_response(inplace=True, is_retry=False)` (client.py:127) is the single low-level POST method every subclass uses via `self.url` / `self.payload`.
  - Token auto-refresh: on a 401 with `detail == "Token has expired."`, calls `self.refresh_token()` (interactive — prompts for username/password via `getpass`, client.py:165-170/authentication.py:68) then retries once. On `"Invalid token."` it instead re-reads the config file (`reinitialise_token`, client.py:182) and retries once — handles the case where another process already refreshed the token on disk. Both paths only retry once (`is_retry` guard); a second failure raises `ATLASAPIClientError`.
  - **Auth note:** token refresh is interactive (blocks on stdin for username/password) and not safe to call inside an unattended/cron pipeline — if you build an automated near-peak trigger and the token expires, the job will hang waiting for `input()`, not fail loudly.

- `ATLASConfigFile` (config.py:7): thin YAML wrapper, requires `token` and `base_url` keys, `.write()` re-serializes the whole file (so don't hand-edit it while a refresh is in flight elsewhere).

- `Token` (authentication.py:23): validates 40-char string. `refresh()` POSTs to `<base_url>auth-token/`.

- List name → ID mapping: `dict_list_id` in utils.py:12 — `{name: [id, getcustomlist_bool]}`. The `bool` distinguishes two separate ID namespaces that happen to share small integers, so e.g. `'good': [2, False]` and `'mookodi': [2, True]` are NOT the same list — `2` means something different in each namespace:
  - `getcustomlist=False` → `id` is a **core detection list ID** (`detection_list_id` field on an object, set server-side, one object can only be in one of these at a time): `garbage=0, follow_up=1, good=2, possible=3, eyeball=4, attic=5, stars=6, agn=7, fasttrack=8, movers=9, magellanic_clouds=10, pm_stars=11, galcand=12, duplicates=13`.
  - `getcustomlist=True` → `id` is a **custom list / object_group ID** (an object can be in any number of these simultaneously, independent of its core detection list): `mookodi=2, mookodi_live=16, cv=40, mdwarf=56, heloise=72, vra=73, dummy=999`.
  - Confirmed live 2026-06-17 against real object `1193736770311803200`: server reports `detection_list_id=4`, matching `eyeball=4` in the core namespace above.

- **VRA score is in the object payload, not a separate query.** Confirmed live 2026-06-17: `RequestSingleSourceData`'s response (`response_data[0]['object']['vra']`) returned `6.2587`, matching the score shown on the web server (6.26) for the same object. Field name is `vra`, not `vra_score`. `RequestMultipleSourceData` entries have the same `entry['object']` shape, so VRA score is available there too — no need for a separate `RequestVRAScores`/`vrascoreslist/` call when you're already pulling source data for other reasons (classification, detection_list_id, lightcurve). `RequestVRAToDoList` is a different thing entirely — it's specifically objects NOT YET garbaged or human-labelled, so anything already routed into Mookodi/Peak/SALT logic won't be on it.

- `response_data` shape: even for a single object, `RequestSingleSourceData.response_data` is a **list** (length 1), not a bare dict — index with `[0]` before reaching `['object']`/`['lc']`/etc. Same entry shape as one element of `RequestMultipleSourceData.response_data`.

## 2. Classes already used in mookodiListWizard.py

| Class | Endpoint | Payload | Notes |
|---|---|---|---|
| `RequestCustomListsTable` (client.py:351) | `objectgroupslist/` | `{'objectgroupid': N}` or `{'objectid': 'id1,id2'}` | READ. Returns rows with `transient_object_id` + `object_group_id`. No chunking logic at all — sends the whole payload in one POST. Fine for "list current members" queries but if a list payload itself ever needs many `objectid`s, there's no chunk wrapper here. |
| `RequestMultipleSourceData` (client.py:495) | `objects/` | `{'objects': 'id1,id2,...', 'mjd': mjdthreshold}` | READ. `chunk_get_response_quiet()` / `chunk_get_response()` split `array_ids` into `chunk_size` pieces (default 100, wizard uses 25), POST each chunk, retry up to `max_retries` (default 3) with random backoff `(1,5)`s, **silently skip** (`logging.error`, no raise) any chunk that exhausts retries (client.py:535-536). A near-peak workflow polling many candidates could silently lose a subset of sources with no exception — only a log line. |
| `WriteToCustomList` (client.py:689) | `objectgroups/` | `{'objectid': 'id1,...', 'objectgroupid': N}` | WRITE. **Has a real bug for batches >100** — see §3. |
| `RemoveFromCustomList` (client.py:742) | `objectgroupsdelete/` | same shape | WRITE/DELETE. Same chunking pattern as above but with `chunk_size` exposed as a constructor arg (default 100) and `response_data` properly initialized to `[]` in `__init__` (client.py:772) — half of the bug in §3 is already fixed here. |

## 3. Root cause: why writes don't chunk (confirmed in source)

The wizard's dev notes say "for WRITE operations chunking just doesn't seem to work at all." Confirmed mechanism in `get_response()` (client.py:127-193):

```python
if self.response.status_code == 200:        # READ success
    if inplace: self.response_data = ...
    else: return self.response.json()       # <-- only branch that RETURNS on inplace=False
elif self.response.status_code == 201:       # WRITE success
    self.response_data = self.response.json()   # always sets attribute, NEVER returns
elif self.response.status_code == 204:       # DELETE success
    self.response_data = 'No Content'            # always sets attribute, NEVER returns
```

Every chunk loop (`_run_chunked_requests` in `RequestMultipleSourceData`, and the analogous methods in `WriteToCustomList`/`RemoveFromCustomList`) calls `_response = self.get_response(inplace=False)` then does `self.response_data.extend(_response)`. This only works for status 200 (reads). For a WRITE (201) or DELETE (204), `get_response(inplace=False)` returns `None` implicitly — so `_response` is `None`, and `.extend(None)` raises `TypeError`. Worse, the inner call has already overwritten `self.response_data` as a side effect (with the JSON dict, or the literal string `'No Content'`), clobbering whatever list was being accumulated across chunks.

This is a real, reproducible bug, not just flaky infra — it's *why* the project policy became "one write per request." It also means:
- `WriteToCustomList.chunk_get_response_quiet()` (client.py:726, triggered automatically whenever `array_ids.shape[0] > 100`, client.py:717) will throw on first chunk past the first.
- `WriteToCustomList.__init__` never initializes `self.response_data = []` at all (unlike `RemoveFromCustomList`, which does at client.py:772) — so even before hitting the `get_response` bug, `self.response_data.extend(...)` on the very first chunk fails because `self.response_data` is still `None` (inherited from `APIClient.__init__`, client.py:89).
- `WriteToCustomList.__init__` also has a separate latent bug: if `array_ids.shape[0] > 100` AND `get_response=True` is passed, it runs `chunk_get_response_quiet()` (which already executes all the POSTs per-chunk) and then *also* calls `self.get_response()` again at the end (client.py:724) using whatever `self.payload` was left over from the last chunk — i.e. a spurious duplicate write of the final chunk.
- No test coverage exists for any of this: `test_client.py` only exercises `chunk_get_response`/`chunk_get_response_quiet` on `RequestMultipleSourceData` (a 200/READ class), and has an explicit `# TODO: write tests for the chunk_get_response methods` (test_client.py:284). The integration write tests (`test_api_write.py`) never call with >100 ids.

**Practical implication for new workflows:** keep doing one-ID-at-a-time writes (as `mookodiListWizard.py` already does via its wrapper functions) until/unless this is fixed upstream. Don't be tempted to pass a big batch into `WriteToCustomList`/`RemoveFromCustomList` even though the chunking code superficially "exists" — it's broken for any batch >100 (>`chunk_size` for the latter).

## 4. Other classes that may matter for near-peak / SALT work

| Class | Endpoint | Purpose | Notes |
|---|---|---|---|
| `RequestSingleSourceData` (client.py:441) | `objects/` | One source's full data incl. lightcurve, by `atlas_id` + optional `mjdthreshold` | Same response shape as one entry of `RequestMultipleSourceData` (`entry['object']['id']`, `['detection_list_id']`, `['observation_status']`, `entry['lc']`). Has `.save_response_to_json()`. |
| `RequestATLASIDsFromWebServerList` (client.py:386) | `objectlist/` | Get all ATLAS IDs currently in a named list | Takes `list_name` (looked up via `dict_list_id`), exposes `.atlas_id_list_str` / `.atlas_id_list_int` cached properties. Simpler than `RequestCustomListsTable` if you just want IDs, not the list metadata. Docstring (client.py:412-415) warns: if your list name isn't in `dict_list_id`, you're stuck — would need to add an entry to utils.py:12 yourself for a new SALT list. |
| `RequestVRAScores` (client.py:278) | `vrascoreslist/` | Read the VRA scoring table by date threshold | Could be useful for re-checking/sorting candidates by score+recency when deciding near-peak triggers, instead of going through custom-list membership. |
| `RequestVRAToDoList` (client.py:316) | `vratodolist/` | Read VRA to-do table by date threshold | Same shape as above. |
| `ConeSearch` (client.py:223) | `cone/` | RA/Dec cone search, `requestType` in `{'all','count','nearest'}`, radius capped at 300 arcsec (warns + presumably clamps server-side, doesn't raise) | Could be relevant if SALT integration ever needs cross-matching by position rather than ATLAS ID. |
| `WriteObjectDetectionListNumber` (client.py:807) | `objectdetectionlist/` | Move an object to a different list **by list number**, not name | Payload: `{'objectid':, 'objectlist': <int>}`. Note this takes the raw list number, unlike the other Write/Remove classes which take `list_name` and resolve via `dict_list_id`. Easy to mix up `objectgroupid` (custom lists, used by WriteToCustomList) vs `objectlist` (detection list, used here) — they are different ID spaces on the server. |
| `WriteToVRAScores` / `WriteToVRARank` / `WriteToToDo` (client.py:574/617/653) | `vrascores/`, `vrarank/`, `vratodo/` | Write VRA pipeline outputs | Docstring explicitly says VRA score writes are one-row-at-a-time only (client.py:583-585) — no chunking attempted here at all, consistent with §3's findings. |

## 5. General gotchas / error-handling patterns

- `parse_atlas_id` (client.py:110) asserts the ID string is exactly 19 characters before `int()`-casting. Test suite confirms this is enforced for `RequestSingleSourceData` but explicitly *not* enforced per-element for `RequestMultipleSourceData`'s array (test_client.py:275-282, marked TODO) — actually it is applied per-element via `self.parse_atlas_id(str(x))` in `RequestMultipleSourceData.__init__` (client.py:509), so a short ID anywhere in the batch will raise an `AssertionError` (not the library's own `ATLASAPIClientError`) and abort the whole batch before any request is sent. Validate your ID list before constructing the object if partial success matters.
- Generic failure mode: `get_response()` raises bare `ATLASAPIClientError(f"Oops, status code is {status}")` (client.py:187) for any status code it doesn't explicitly handle (not 200/201/204/401-with-detail) — i.e. 400/403/500 all collapse into one generic message with no body detail surfaced. You'll want to catch and log `self.response.text` yourself if you need to debug a 500 from inside a new workflow.
- `RequestMultipleSourceData`/chunked write loops swallow exceptions per-chunk down to a log line after `max_retries` (client.py:536, 804-805) — no exception propagates, so a calling script sees a "successful" run that's silently missing data. Worth wrapping with your own post-hoc count check (e.g. compare `len(response_data)` to expected) in any new pipeline, same as the wizard script already does implicitly by checking response lengths.
- `ConeSearch.verify_payload` only warns (doesn't clamp or raise) if radius > 300″ — read the warning text again: it says values will be "rounded down" server-side, but the client itself does not modify the payload, so if you suppress warnings you won't notice the server silently capped your radius.

## 6. API surface map

| Class | Purpose | Key params | Gotcha |
|---|---|---|---|
| `APIClient` | Base class, auth/session | `api_config_file`, `auto_refresh_fl` | Token refresh is interactive (`input()`/`getpass`) — unsafe in unattended pipelines |
| `ConeSearch` | RA/Dec cone search | `payload{ra,dec,radius,requestType}` | radius>300″ only warns, doesn't clamp client-side |
| `RequestVRAScores` | Read VRA scores table | `payload{datethreshold}` | — |
| `RequestVRAToDoList` | Read VRA to-do table | `payload{datethreshold}` | — |
| `RequestCustomListsTable` | Read custom list membership | `payload{objectgroupid}` or `{objectid}` | No chunking; single POST regardless of payload size |
| `RequestATLASIDsFromWebServerList` | Get all IDs in a named list | `list_name` | Unknown list names need a manual entry in `dict_list_id` (utils.py:12) |
| `RequestSingleSourceData` | Full data for one source | `atlas_id`, `mjdthreshold` | `atlas_id` must be exactly 19 digits |
| `RequestMultipleSourceData` | Full data for many sources | `array_ids`, `mjdthreshold`, `chunk_size` | Failed chunks are silently dropped after retries, only logged |
| `WriteToVRAScores` | Write VRA score row | `payload` | One row at a time only, by design |
| `WriteToVRARank` | Write VRA rank row | `payload` | One row at a time only |
| `WriteToToDo` | Write to VRA to-do table | `payload{objectid}` | — |
| `WriteToCustomList` | Add IDs to a custom list | `array_ids`, `list_name` | **Broken for batches >100**: chunked path crashes (uninitialized `response_data`, plus `get_response(inplace=False)` never returns on 201) and double-fires the last chunk if `get_response=True` |
| `RemoveFromCustomList` | Remove IDs from a custom list | `array_ids`, `list_name`, `chunk_size` | Same `get_response(inplace=False)`/201/204 bug as above on chunks past the first; `response_data` is initialized here so the crash mode differs slightly but batches >`chunk_size` are still unreliable |
| `WriteObjectDetectionListNumber` | Move object between detection lists by number | `payload{objectid, objectlist}` | Uses a different ID space (`objectlist` int) than `dict_list_id`'s `object_group_id` — don't confuse the two |

## 7. Bottom line for this project

The "one-write-at-a-time" pattern in `mookodiListWizard.py` isn't a stylistic workaround — it's the only path through this client that's actually exercised by tests and doesn't hit the `inplace=False`/201/204 bug in `get_response()`. Any new workflow (near-peak trigger, SALT link) that needs to write more than a handful of IDs should keep using single-ID calls, or budget time to fix `get_response()` upstream (the fix is small: make the 201/204 branches respect `inplace` the same way the 200 branch does) before relying on the batch path.
