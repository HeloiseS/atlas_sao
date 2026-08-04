# Slack Report Bot — Design Spec

**Date:** 2026-08-04
**Status:** Approved for implementation planning

## Purpose

Cycle 2 goal (raised 2026-07-31, unblocked 2026-08-04): read SALT/Mookodi
observation-report activity out of the `#atlas_sao_bot` Slack channel and
into the same SQLite bookkeeping DB (`db/log.db`) the other wizards already
write to, so we can eventually compare what's going into our custom lists
against what's actually being sent to/observed by the telescopes.

Two message sources currently land in that channel:

1. **Bot messages** from Nic's "ATLAS SALT Triggers" Slack app — structured
   (Block Kit) notifications of targets newly visible at SALT, posted per
   trigger batch. Today SALT-only; Nic is consolidating to a single
   reporting bot covering all telescopes.
2. **Human messages** — a person (Simon/Nic) posting free text confirming a
   trigger actually happened. Keyword/phrasing convention not yet agreed
   between H and the telescope team.

## Scope for this iteration

**In scope:**
- Wizard script + cron wrapper skeleton, matching the existing
  `mookodiListWizard.py` / `saltListWizard.py` pattern.
- Polling read of new channel messages since the last run.
- Parsing bot messages' `blocks` payload for `atlas_id`, `ra`, `dec`,
  `latest_mag`, and message time.
- New `slack_messages` bookkeeping table + migration SQL.
- Sender identification (`sender_id`/`sender_name`), with a
  telescope/related_list fallback lookup keyed on sender identity.
- Tests against captured sample Slack API responses (bot + human fixtures).

**Out of scope (explicitly deferred):**
- Parsing human message content — blocked on H/Nic/Simon agreeing a
  keyword convention.
- ATLAS-name → ATLAS-ID resolution. Nic's bot is expected to always
  include the integer `atlas_id` going forward (H is following up with
  him); we do not parse or store the ATLAS name.
- Actually running the prod DB migration — H does this herself on db1,
  same as the `xtgal_watchlist` rename.

## Architecture

New module `atlas_sao/slackReportWizard.py`, alongside the existing
wizards. New wrapper `bash_prod/slackReportWizard.sh`, same
flock-lock-file + env/PYTHONPATH pattern as
`bash_prod/mookodiListWizard.sh`. Cron-invoked periodic polling (not a
long-running Events API/Socket Mode process) — consistent with the
existing wizards' operational model, no new persistent service to run on
db1.

## Data flow

1. Read `MAX(slack_ts)` from `slack_messages` as the polling cursor (no
   separate state file needed).
2. Call Slack's `conversations.history` on `#atlas_sao_bot` with
   `oldest=<cursor>`, paginating if needed.
3. For each message, resolve `sender_id`/`sender_name` (from `bot_id` or
   `user`, via `bots.info`/`users.info` as needed). Presence of `bot_id`
   on the message is what determines bot vs. human below.
4. If the message has a `bot_id` (bot-sent): parse `blocks` for `atlas_id`,
   `ra`, `dec`, `latest_mag`, message time. Store the raw `blocks` JSON.
   Parsing failures (missing/unexpected fields) are caught per-message,
   logged, and the row is still stored with whatever parsed fields
   succeeded (rest NULL) — one bad message must not block the run or
   drop other messages.
5. If the message has no `bot_id` (human-sent): store `raw_text` only,
   no parsing.
6. For `telescope`/`related_list`: prefer explicit fields in the message
   `blocks` if present (Nic's planned programmatic field); otherwise fall
   back to a sender_id-keyed lookup table in config. This degrades
   gracefully as Nic's bot evolves from SALT-only to a unified multi-
   telescope reporter — no code change needed when the real fields land,
   just stop hitting the fallback.
7. `INSERT OR IGNORE` keyed on `slack_ts` (Slack's per-channel-unique
   timestamp) — makes reruns/overlapping polls idempotent.

## Schema

New table in `db/log.sql` / `db/log.db`:

```sql
CREATE TABLE slack_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slack_ts      TEXT NOT NULL UNIQUE,
    sender_id     TEXT NOT NULL,
    sender_name   TEXT NOT NULL,
    telescope     TEXT,             -- from message blocks if present, else sender lookup, else NULL
    related_list  TEXT,             -- from message blocks if present, else sender lookup, else NULL
    raw_text      TEXT,             -- human messages only
    raw_blocks    TEXT,             -- bot messages only, JSON
    atlas_id      INTEGER,
    ra            REAL,
    dec           REAL,
    latest_mag    REAL,
    message_time  TEXT,             -- UTC, derived from slack_ts
    timestamp     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`sender_id` is Slack's permanent bot/user ID (display names are editable,
IDs aren't) — it's the reliable key for the telescope/related_list
fallback lookup, `sender_name` is purely the human-readable label.

Neither `raw_text` nor `raw_blocks` is redundant per row: bot rows only
populate `raw_blocks` (the flattened-text fallback is a squished,
hard-to-read rendering of the same data — see the sample message in the
brainstorming log); human rows only populate `raw_text` (they have no
Block Kit content).

## Config/secrets

New gitignored `slack_config_MINE.yaml` (same pattern as
`api_config_MINE.yaml`), referenced via a `CONFIG_SLACK` env var:
- Bot token
- Channel ID
- Sender → (telescope, related_list) fallback lookup

An existing Slack app/bot token is already available for this
integration; may need its OAuth scopes checked/extended for
`conversations.history` read access — first implementation step should
confirm this by fetching one real sample message.

## Testing

Unit tests with mocked Slack API responses:
- A captured real sample bot message (first implementation step: fetch
  one via the Slack API to get the actual `blocks` shape — we're
  currently working from a flattened-text example only) and a sample
  human message, used as fixtures.
- Parse success path.
- Missing/malformed `atlas_id` in a bot message (parse-failure
  resilience).
- Unknown sender (no fallback lookup entry) → `telescope`/`related_list`
  NULL, row still stored.
- Duplicate `slack_ts` re-insert is a no-op (idempotency).

No live Slack token required for tests, consistent with how the other
wizards are tested against `atlasapiclient`.

## Dependencies

Add `slack_sdk` to `pyproject.toml`.
