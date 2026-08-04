# Slack Report Bot Implementation Plan

**Goal:** Build the `slackReportWizard.py` skeleton that polls `#atlas_sao_bot`, parses Nic's bot trigger messages, and logs both bot and human messages into a new `slack_messages` bookkeeping table.

**Architecture:** One new wizard module (`atlas_sao/slackReportWizard.py`) matching the existing wizard pattern, backed by a new SQLite table and a small config loader. Bot messages are parsed from Slack's `blocks` payload (not the flattened text). See `docs/superpowers/specs/2026-08-04-slack-report-bot-design.md` for full rationale.

**Tech Stack:** Python, `slack_sdk` (new dependency), sqlite3, pytest.

## Global Constraints

- No docstrings/comments unless the WHY is non-obvious (H's code style — see CLAUDE.md).
- Human message content parsing is out of scope (keyword convention not agreed).
- ATLAS-name→ID resolution is out of scope — if `id` isn't a plain integer, `atlas_id` stays NULL.
- The actual prod DB migration is run by H on db1, not part of this plan.

---

### Task 1: Slack config + capture a real sample message

**Files:**
- Modify: `pyproject.toml` (add `slack_sdk` dependency)
- Modify: `.gitignore` (ignore `slack_config_MINE.yaml`)
- Create: `atlas_sao/config_files/slack_config_template.yaml`
- Create: `atlas_sao/slack_config.py`
- Create: `tests/test_slack_config.py`
- Create: `scripts/fetch_slack_sample.py`

**Interfaces:**
- Produces: `load_slack_config(config_path: str = None) -> dict`, used by every later task.

Steps:

1. Add the dependency:

```toml
dependencies = [
    "atlasapiclient",
    "numpy",
    "pandas",
    "slack_sdk",
]
```

2. Add to `.gitignore` (near the existing `api_config_MINE.yaml` line):

```
slack_config_MINE.yaml
```

3. Create `atlas_sao/config_files/slack_config_template.yaml`:

```yaml
bot_token: "xoxb-put-your-bot-token-here"
channel_id: "Cxxxxxxxxxx"
sender_lookup:
  Uxxxxxxxxxx:
    telescope: "SALT"
    related_list: "south_transients_100mpc"
```

4. Create `atlas_sao/slack_config.py`:

```python
import os
import yaml

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), 'config_files', 'slack_config_MINE.yaml'
)


def load_slack_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = os.environ.get('CONFIG_SLACK', DEFAULT_CONFIG_PATH)
    with open(config_path) as f:
        return yaml.safe_load(f)
```

5. Write `tests/test_slack_config.py`:

```python
import atlas_sao.slack_config as slack_config


def test_loads_yaml_contents(tmp_path):
    config_file = tmp_path / 'slack_config_test.yaml'
    config_file.write_text('bot_token: "xoxb-test"\nchannel_id: "C123"\n')
    config = slack_config.load_slack_config(str(config_file))
    assert config['bot_token'] == 'xoxb-test'
    assert config['channel_id'] == 'C123'


def test_env_var_override(tmp_path, monkeypatch):
    config_file = tmp_path / 'slack_config_test.yaml'
    config_file.write_text('bot_token: "xoxb-test"\nchannel_id: "C123"\n')
    monkeypatch.setenv('CONFIG_SLACK', str(config_file))
    config = slack_config.load_slack_config()
    assert config['bot_token'] == 'xoxb-test'
```

6. Run: `pytest tests/test_slack_config.py -v` — expect both to pass.

7. Copy `atlas_sao/config_files/slack_config_template.yaml` to
   `atlas_sao/config_files/slack_config_MINE.yaml` and fill in your real bot
   token and the `#atlas_sao_bot` channel ID (you can get the channel ID
   from Slack's channel details pane, "Copy channel ID"). Leave
   `sender_lookup` empty for now.

8. Create `scripts/fetch_slack_sample.py`:

```python
import json
from slack_sdk import WebClient
from atlas_sao.slack_config import load_slack_config

config = load_slack_config()
client = WebClient(token=config['bot_token'])
resp = client.conversations_history(channel=config['channel_id'], limit=10)
print(json.dumps(resp['messages'], indent=2))
```

9. **H runs this herself** (needs her live token/channel):
   `python scripts/fetch_slack_sample.py > /tmp/slack_sample.json`, then
   inspects the output and pastes back: one message from Nic's "ATLAS SALT
   Triggers" bot (has a `bot_id` key) and, if one exists in the last 10, one
   human message (no `bot_id`, has a `user` key instead).

10. Save the single bot message object H pastes back as
    `tests/fixtures/slack_sample_bot_message.json`, and the human one (if
    captured) as `tests/fixtures/slack_sample_human_message.json`. If no
    human message shows up in the sample, write a minimal realistic one by
    hand for the fixture (`{"type": "message", "user": "U123", "ts":
    "1690833945.001900", "text": "SALT confirms trigger on 2026abc"}`) —
    note in a code comment that it's synthetic, not captured.

11. Commit:

```bash
git add pyproject.toml .gitignore atlas_sao/config_files/slack_config_template.yaml \
    atlas_sao/slack_config.py tests/test_slack_config.py scripts/fetch_slack_sample.py \
    tests/fixtures/slack_sample_bot_message.json tests/fixtures/slack_sample_human_message.json
git commit -m "Add Slack config loader and capture a real sample message"
```

---

### Task 2: `slack_messages` table + db.py functions

**Files:**
- Modify: `db/log.sql` (new table)
- Modify: `atlas_sao/db.py` (new functions)
- Modify: `tests/test_db.py` (new test classes — reuses the existing `db_path` fixture already in that file)

**Interfaces:**
- Consumes: `db.get_connection` (existing).
- Produces: `db.log_slack_message(slack_ts, sender_id, sender_name, telescope=None, related_list=None, raw_text=None, raw_blocks=None, atlas_id=None, ra=None, dec=None, latest_mag=None, message_time=None, db_path=None) -> None` and `db.get_last_slack_ts(db_path=None) -> str | None`, both used by Task 6.

Steps:

1. Append to `db/log.sql`:

```sql
CREATE TABLE slack_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slack_ts      TEXT NOT NULL UNIQUE,
    sender_id     TEXT NOT NULL,
    sender_name   TEXT NOT NULL,
    telescope     TEXT,
    related_list  TEXT,
    raw_text      TEXT,
    raw_blocks    TEXT,
    atlas_id      INTEGER,
    ra            REAL,
    dec           REAL,
    latest_mag    REAL,
    message_time  TEXT,
    timestamp     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

2. Add to `atlas_sao/db.py`:

```python
def log_slack_message(slack_ts: str,
                       sender_id: str,
                       sender_name: str,
                       telescope: str = None,
                       related_list: str = None,
                       raw_text: str = None,
                       raw_blocks: str = None,
                       atlas_id: int = None,
                       ra: float = None,
                       dec: float = None,
                       latest_mag: float = None,
                       message_time: str = None,
                       db_path: str = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO slack_messages '
            '(slack_ts, sender_id, sender_name, telescope, related_list, '
            'raw_text, raw_blocks, atlas_id, ra, dec, latest_mag, message_time) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (slack_ts, sender_id, sender_name, telescope, related_list,
             raw_text, raw_blocks, atlas_id, ra, dec, latest_mag, message_time)
        )

    conn.close()


def get_last_slack_ts(db_path: str = None) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute('SELECT MAX(slack_ts) FROM slack_messages').fetchone()

    conn.close()
    return row[0]
```

3. Append to `tests/test_db.py` (uses the file's existing `db_path` fixture):

```python
class TestLogSlackMessage:
    def test_inserts_row(self, db_path):
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers',
                              telescope='SALT', atlas_id=1120650750361606600,
                              db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_id, sender_name, telescope, atlas_id FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row == ('B123', 'ATLAS SALT Triggers', 'SALT', 1120650750361606600)

    def test_duplicate_slack_ts_is_noop(self, db_path):
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM slack_messages').fetchone()[0]
        conn.close()
        assert count == 1


class TestGetLastSlackTs:
    def test_returns_none_when_empty(self, db_path):
        assert db.get_last_slack_ts(db_path=db_path) is None

    def test_returns_max_ts(self, db_path):
        db.log_slack_message('1690833945.001900', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        db.log_slack_message('1690834000.000100', 'B123', 'ATLAS SALT Triggers', db_path=db_path)
        assert db.get_last_slack_ts(db_path=db_path) == '1690834000.000100'
```

4. Run: `pytest tests/test_db.py -v` — expect all (old + new) to pass.

5. Commit:

```bash
git add db/log.sql atlas_sao/db.py tests/test_db.py
git commit -m "Add slack_messages table and bookkeeping functions"
```

---

### Task 3: Sender resolution + telescope/list fallback

**Files:**
- Create: `atlas_sao/slackReportWizard.py`
- Create: `tests/test_slack_report_wizard.py`

**Interfaces:**
- Produces: `resolve_sender(message: dict, client, cache: dict) -> tuple[str, str]` and
  `resolve_telescope_and_list(sender_id: str, parsed_fields: dict, sender_lookup: dict) -> tuple[str | None, str | None]`,
  both used by Task 6.

Steps:

1. Start `atlas_sao/slackReportWizard.py`:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)


def resolve_sender(message: dict, client, cache: dict) -> tuple:
    if 'bot_id' in message:
        sender_id = message['bot_id']
        if sender_id not in cache:
            info = client.bots_info(bot=sender_id)
            cache[sender_id] = info['bot']['name']
    else:
        sender_id = message['user']
        if sender_id not in cache:
            info = client.users_info(user=sender_id)
            cache[sender_id] = info['user']['real_name']

    return sender_id, cache[sender_id]


def resolve_telescope_and_list(sender_id: str, parsed_fields: dict, sender_lookup: dict) -> tuple:
    telescope = parsed_fields.get('telescope')
    related_list = parsed_fields.get('related_list')

    if telescope is None or related_list is None:
        fallback = sender_lookup.get(sender_id, {})
        telescope = telescope or fallback.get('telescope')
        related_list = related_list or fallback.get('related_list')

    return telescope, related_list
```

2. Write `tests/test_slack_report_wizard.py`:

```python
from unittest.mock import MagicMock
import atlas_sao.slackReportWizard as wizard


class TestResolveSender:
    def test_bot_message_resolves_and_caches(self):
        client = MagicMock()
        client.bots_info.return_value = {'bot': {'name': 'ATLAS SALT Triggers'}}
        cache = {}

        sender_id, sender_name = wizard.resolve_sender({'bot_id': 'B123'}, client, cache)
        assert (sender_id, sender_name) == ('B123', 'ATLAS SALT Triggers')

        wizard.resolve_sender({'bot_id': 'B123'}, client, cache)
        client.bots_info.assert_called_once()

    def test_human_message_resolves_via_users_info(self):
        client = MagicMock()
        client.users_info.return_value = {'user': {'real_name': 'Simon de Wet'}}
        cache = {}

        sender_id, sender_name = wizard.resolve_sender({'user': 'U456'}, client, cache)
        assert (sender_id, sender_name) == ('U456', 'Simon de Wet')


class TestResolveTelescopeAndList:
    def test_uses_parsed_fields_when_present(self):
        result = wizard.resolve_telescope_and_list(
            'B123', {'telescope': 'SALT', 'related_list': 'south_transients_100mpc'}, {}
        )
        assert result == ('SALT', 'south_transients_100mpc')

    def test_falls_back_to_sender_lookup(self):
        lookup = {'B123': {'telescope': 'SALT', 'related_list': 'south_transients_100mpc'}}
        result = wizard.resolve_telescope_and_list('B123', {}, lookup)
        assert result == ('SALT', 'south_transients_100mpc')

    def test_unknown_sender_returns_none(self):
        result = wizard.resolve_telescope_and_list('B999', {}, {})
        assert result == (None, None)
```

3. Run: `pytest tests/test_slack_report_wizard.py -v` — expect all to pass.

4. Commit:

```bash
git add atlas_sao/slackReportWizard.py tests/test_slack_report_wizard.py
git commit -m "Add Slack sender resolution and telescope/list fallback lookup"
```

---

### Task 4: Bot message block parser

**Files:**
- Modify: `atlas_sao/slackReportWizard.py`
- Modify: `tests/test_slack_report_wizard.py`
- Read: `tests/fixtures/slack_sample_bot_message.json` (from Task 1)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `parse_bot_message(message: dict) -> dict` (keys: `telescope`, `related_list`, `atlas_id`, `ra`, `dec`, `latest_mag`), used by Task 6.

The parser below assumes Slack's standard Block Kit `section`/`fields` shape
(each field is `{"type": "mrkdwn", "text": "*Label*\nValue"}`), inferred
from the flattened-text sample in the design spec. **Before finishing this
task, open `tests/fixtures/slack_sample_bot_message.json` (captured in Task
1 from the real channel) and confirm its `blocks` actually look like this.**
If Nic's real field labels differ from `id` / `RA / Dec` / `Latest` below,
update the label strings in `parse_bot_message` (not the parsing logic
itself) to match reality, and add a matching test case using the real
fixture.

Steps:

1. Add to `atlas_sao/slackReportWizard.py`:

```python
def parse_blocks_fields(blocks: list) -> dict:
    fields = {}
    for block in blocks:
        if block.get('type') != 'section':
            continue
        for field in block.get('fields', []):
            text = field.get('text', '')
            if text.startswith('*') and '\n' in text:
                label, _, value = text.partition('\n')
                fields[label.strip('*').strip()] = value.strip()
    return fields


def parse_bot_message(message: dict) -> dict:
    fields = parse_blocks_fields(message.get('blocks', []))

    parsed = {
        'telescope': fields.get('telescope'),
        'related_list': fields.get('related_list'),
        'atlas_id': None,
        'ra': None,
        'dec': None,
        'latest_mag': None,
    }

    raw_id = fields.get('id')
    if raw_id is not None:
        try:
            parsed['atlas_id'] = int(raw_id.strip())
        except ValueError:
            logging.warning(f"Slack bot message 'id' field not an integer, skipping atlas_id: {raw_id!r}")

    radec = fields.get('RA / Dec')
    if radec and ',' in radec:
        try:
            ra_str, dec_str = radec.split(',', 1)
            parsed['ra'] = float(ra_str.strip())
            parsed['dec'] = float(dec_str.strip())
        except ValueError:
            logging.warning(f"Slack bot message 'RA / Dec' field not parseable: {radec!r}")

    latest = fields.get('Latest')
    if latest:
        try:
            parsed['latest_mag'] = float(latest.split()[0])
        except (ValueError, IndexError):
            logging.warning(f"Slack bot message 'Latest' field not parseable: {latest!r}")

    return parsed
```

2. Append to `tests/test_slack_report_wizard.py`:

```python
import json
import os

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class TestParseBotMessage:
    def test_parses_id_ra_dec_latest_mag(self):
        message = {
            'bot_id': 'B123',
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*id*\n1120650750361606600'},
                    {'type': 'mrkdwn', 'text': '*RA / Dec*\n181.71149, -36.26852'},
                    {'type': 'mrkdwn', 'text': '*Latest*\n16.36 o · 2026-07-31 17:45:45 UTC'},
                ]}
            ]
        }
        parsed = wizard.parse_bot_message(message)
        assert parsed['atlas_id'] == 1120650750361606600
        assert parsed['ra'] == 181.71149
        assert parsed['dec'] == -36.26852
        assert parsed['latest_mag'] == 16.36

    def test_non_integer_id_leaves_atlas_id_none(self):
        message = {
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*id*\nATLAS26jri'},
                ]}
            ]
        }
        parsed = wizard.parse_bot_message(message)
        assert parsed['atlas_id'] is None

    def test_missing_fields_all_none(self):
        parsed = wizard.parse_bot_message({'blocks': []})
        assert parsed == {
            'telescope': None, 'related_list': None,
            'atlas_id': None, 'ra': None, 'dec': None, 'latest_mag': None,
        }

    def test_real_sample_fixture_parses_without_error(self):
        message = load_fixture('slack_sample_bot_message.json')
        parsed = wizard.parse_bot_message(message)
        assert isinstance(parsed, dict)
```

3. Run: `pytest tests/test_slack_report_wizard.py -v` — expect all to pass.
   If `test_real_sample_fixture_parses_without_error` reveals the real
   labels differ (e.g. `parsed['atlas_id']` stays `None` when the fixture
   clearly has an id), fix the label strings in `parse_bot_message` per the
   note above and add an assertion on the real value before moving on.

4. Commit:

```bash
git add atlas_sao/slackReportWizard.py tests/test_slack_report_wizard.py
git commit -m "Add Slack bot message block parser"
```

---

### Task 5: Wizard orchestration (polling loop)

**Files:**
- Modify: `atlas_sao/slackReportWizard.py`
- Modify: `tests/test_slack_report_wizard.py`

**Interfaces:**
- Consumes: `resolve_sender`, `resolve_telescope_and_list`, `parse_bot_message` (Tasks 3-4), `db.log_slack_message`, `db.get_last_slack_ts` (Task 2), `load_slack_config` (Task 1).
- Produces: `process_message(message, client, sender_cache, sender_lookup) -> None`, `fetch_new_messages(client, channel_id, oldest) -> list`, and the `if __name__ == "__main__"` entry point.

Steps:

1. Add to the top of `atlas_sao/slackReportWizard.py`:

```python
import json
from datetime import datetime, timezone
from slack_sdk import WebClient
import atlas_sao.db as db
from atlas_sao.slack_config import load_slack_config
```

2. Add to `atlas_sao/slackReportWizard.py`:

```python
def message_time_from_ts(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def fetch_new_messages(client, channel_id: str, oldest: str) -> list:
    messages = []
    cursor = None
    while True:
        kwargs = {'channel': channel_id, 'limit': 200}
        if oldest:
            kwargs['oldest'] = oldest
        if cursor:
            kwargs['cursor'] = cursor
        resp = client.conversations_history(**kwargs)
        messages.extend(resp['messages'])
        cursor = resp.get('response_metadata', {}).get('next_cursor')
        if not cursor:
            break
    return messages


def process_message(message: dict, client, sender_cache: dict, sender_lookup: dict) -> None:
    sender_id, sender_name = resolve_sender(message, client, sender_cache)

    if 'bot_id' in message:
        parsed = parse_bot_message(message)
        raw_text = None
        raw_blocks = json.dumps(message.get('blocks', []))
    else:
        parsed = {'telescope': None, 'related_list': None, 'atlas_id': None, 'ra': None, 'dec': None, 'latest_mag': None}
        raw_text = message.get('text')
        raw_blocks = None

    telescope, related_list = resolve_telescope_and_list(sender_id, parsed, sender_lookup)

    db.log_slack_message(
        slack_ts=message['ts'],
        sender_id=sender_id,
        sender_name=sender_name,
        telescope=telescope,
        related_list=related_list,
        raw_text=raw_text,
        raw_blocks=raw_blocks,
        atlas_id=parsed['atlas_id'],
        ra=parsed['ra'],
        dec=parsed['dec'],
        latest_mag=parsed['latest_mag'],
        message_time=message_time_from_ts(message['ts']),
    )


if __name__ == "__main__":
    config = load_slack_config()
    client = WebClient(token=config['bot_token'])
    sender_lookup = config.get('sender_lookup', {})

    oldest = db.get_last_slack_ts()
    messages = fetch_new_messages(client, config['channel_id'], oldest)
    logging.info(f"Fetched {len(messages)} new Slack messages.")

    sender_cache = {}
    for message in messages:
        try:
            process_message(message, client, sender_cache, sender_lookup)
        except Exception:
            logging.exception(f"Failed to process Slack message ts={message.get('ts')}")
```

Note: Slack's `oldest` parameter is not guaranteed exclusive across API
versions — relying on `slack_messages.slack_ts`'s `UNIQUE` constraint (via
`INSERT OR IGNORE`) to make re-processing the boundary message a safe no-op,
rather than relying on exact `oldest` semantics.

3. Append to `tests/test_slack_report_wizard.py`:

```python
class TestProcessMessage:
    def test_bot_message_logs_parsed_fields(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / 'test.db')
        import sqlite3, os
        conn = sqlite3.connect(db_path)
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'log.sql')
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.close()
        monkeypatch.setattr(db, 'get_connection', lambda path=None: sqlite3.connect(db_path))

        client = MagicMock()
        client.bots_info.return_value = {'bot': {'name': 'ATLAS SALT Triggers'}}
        message = {
            'bot_id': 'B123',
            'ts': '1690833945.001900',
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*id*\n1120650750361606600'},
                ]}
            ],
        }

        wizard.process_message(message, client, {}, {'B123': {'telescope': 'SALT', 'related_list': 'south_transients_100mpc'}})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, telescope, related_list, atlas_id, raw_text FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row == ('ATLAS SALT Triggers', 'SALT', 'south_transients_100mpc', 1120650750361606600, None)

    def test_human_message_logs_raw_text_only(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / 'test.db')
        import sqlite3, os
        conn = sqlite3.connect(db_path)
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'log.sql')
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.close()
        monkeypatch.setattr(db, 'get_connection', lambda path=None: sqlite3.connect(db_path))

        client = MagicMock()
        client.users_info.return_value = {'user': {'real_name': 'Simon de Wet'}}
        message = {'user': 'U456', 'ts': '1690833945.001900', 'text': 'SALT confirms trigger on 2026abc'}

        wizard.process_message(message, client, {}, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, telescope, atlas_id, raw_text FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row == ('Simon de Wet', None, None, 'SALT confirms trigger on 2026abc')
```

4. Run: `pytest tests/test_slack_report_wizard.py -v` — expect all to pass.

5. Commit:

```bash
git add atlas_sao/slackReportWizard.py tests/test_slack_report_wizard.py
git commit -m "Add Slack report wizard polling loop and entry point"
```

---

### Task 6: Prod wrapper + README

**Files:**
- Create: `bash_prod/slackReportWizard.sh`
- Modify: `README.md`

Steps:

1. Create `bash_prod/slackReportWizard.sh` (mirrors `bash_prod/mookodiListWizard.sh`):

```bash
#!/bin/bash

# SLACK REPORT WIZARD
# --------------------
#
# Wrapper script that sets the environment and the python path
# then calls the python script (in the atlas_sao package).

LOCKFILE="$(dirname "$0")/.locks/slackReportWizard.lock"
mkdir -p "$(dirname "$LOCKFILE")"
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Previous run still in progress, skipping."; exit 1; }

export PYTHONPATH=/home/atlas/code/atlasapiclient
export PYTHONPATH="${PYTHONPATH}:/home/atlas/code/atlas_sao"
export CONFIG_SLACK=/home/atlas/code/atlas_sao/atlas_sao/config_files/slack_config_MINE.yaml

echo "Polling #atlas_sao_bot for new messages."
t_start=$(date +%s)
/home/atlas/anaconda3/envs/vra/bin/python /home/atlas/code/atlas_sao/atlas_sao/slackReportWizard.py
t_end=$(date +%s)

echo "Finished polling Slack."
delta_t=$((t_end - t_start))

echo "Slack report wizard took $delta_t seconds."
```

2. `chmod +x bash_prod/slackReportWizard.sh`

3. Add a section to `README.md` (after the existing Mookodi Transients at
   Peak section), documenting: what `slack_messages` records, that
   `telescope`/`related_list` come from the message content when present,
   else from `sender_lookup` in the config, and that human message content
   isn't parsed yet.

```markdown
## Slack Report Bot

Custom monitoring of `#atlas_sao_bot`, where Nic's "ATLAS SALT Triggers"
bot posts newly-visible SALT targets and humans post free-text trigger
confirmations.

**Script**: `slackReportWizard.py`
- Polls the channel for messages since the last recorded `slack_ts`.
- Bot messages (identified by Slack's `bot_id`): parses the message's
  `blocks` for `atlas_id`, `ra`, `dec`, `latest_mag`; raw `blocks` JSON
  kept for reparsing if the format changes.
- Human messages: raw text only — content parsing is blocked on agreeing
  a keyword convention with the telescope team.
- `telescope`/`related_list` come from explicit fields in the message if
  present, otherwise from the `sender_lookup` table in
  `slack_config_MINE.yaml` (keyed on Slack's permanent `sender_id`, not
  the editable display name).

### `slack_messages`

Logged via `db.log_slack_message()`, deduplicated on `slack_ts`.
```

4. Commit:

```bash
git add bash_prod/slackReportWizard.sh README.md
git commit -m "Add Slack report wizard prod wrapper and docs"
```
