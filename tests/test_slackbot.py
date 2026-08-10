import json
import os
from unittest.mock import MagicMock
import atlas_sao.db as db
import atlas_sao.slackbot as slackbot

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class TestResolveSender:
    def test_bot_message_resolves_from_bot_profile(self):
        client = MagicMock()
        message = {'bot_id': 'B123', 'bot_profile': {'name': 'ATLAS SALT Triggers'}}
        cache = {}

        sender_id, sender_name = slackbot.resolve_sender(message, client, cache)
        assert (sender_id, sender_name) == ('B123', 'ATLAS SALT Triggers')
        client.bots_info.assert_not_called()

    def test_human_message_resolves_via_users_info(self):
        client = MagicMock()
        client.users_info.return_value = {'user': {'real_name': 'Simon de Wet'}}
        cache = {}

        sender_id, sender_name = slackbot.resolve_sender({'user': 'U456'}, client, cache)
        assert (sender_id, sender_name) == ('U456', 'Simon de Wet')

    def test_human_message_caches_across_calls(self):
        client = MagicMock()
        client.users_info.return_value = {'user': {'real_name': 'Simon de Wet'}}
        cache = {}

        slackbot.resolve_sender({'user': 'U456'}, client, cache)
        slackbot.resolve_sender({'user': 'U456'}, client, cache)
        client.users_info.assert_called_once()

    def test_bot_message_without_profile_resolves_via_bots_info(self):
        client = MagicMock()
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        cache = {}

        sender_id, sender_name = slackbot.resolve_sender({'bot_id': 'B0BN0APFTC0'}, client, cache)
        assert (sender_id, sender_name) == ('B0BN0APFTC0', 'Southern Triggers')
        client.bots_info.assert_called_once_with(bot='B0BN0APFTC0')


class TestParseBlocksFields:
    def test_extracts_labelled_fields(self):
        blocks = [
            {'type': 'section', 'fields': [
                {'type': 'mrkdwn', 'text': '*RA / Dec*\n181.71149, -36.26852'},
                {'type': 'mrkdwn', 'text': '*Latest*\n16.36 o · 2026-07-31 17:45:45 UT'},
            ]}
        ]
        fields = slackbot.parse_blocks_fields(blocks)
        assert fields == {
            'RA / Dec': '181.71149, -36.26852',
            'Latest': '16.36 o · 2026-07-31 17:45:45 UT',
        }

    def test_ignores_non_section_blocks(self):
        blocks = [
            {'type': 'header', 'text': {'type': 'plain_text', 'text': 'not a field'}},
            {'type': 'divider'},
        ]
        assert slackbot.parse_blocks_fields(blocks) == {}

    def test_empty_blocks_returns_empty_dict(self):
        assert slackbot.parse_blocks_fields([]) == {}


class TestParseTelescopeFromText:
    def test_matches_salt_case_insensitive(self):
        assert slackbot.parse_telescope_from_text('ATLAS Transient SALT requests: 2 new target(s)') == 'SALT'
        assert slackbot.parse_telescope_from_text('atlas transient salt requests') == 'SALT'

    def test_matches_mookodi_case_insensitive(self):
        assert slackbot.parse_telescope_from_text('ATLAS Transient Mookodi requests') == 'Mookodi'
        assert slackbot.parse_telescope_from_text('atlas transient MOOKODI requests') == 'Mookodi'

    def test_no_match_returns_none(self):
        assert slackbot.parse_telescope_from_text('ATLAS Transient requests') is None


class TestParseBotMessage:
    def test_parses_id_ra_dec_latest_mag(self):
        message = {
            'bot_id': 'B123',
            'text': 'ATLAS Transient SALT requests: 1 new target(s)',
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*ATLAS ID*\n1120650750361606600'},
                    {'type': 'mrkdwn', 'text': '*RA / Dec*\n181.71149, -36.26852'},
                    {'type': 'mrkdwn', 'text': '*Latest*\n16.36 o · 2026-07-31 17:45:45 UT'},
                ]}
            ]
        }
        parsed = slackbot.parse_bot_message(message)
        assert parsed['atlas_id'] == 1120650750361606600
        assert parsed['ra'] == 181.71149
        assert parsed['dec'] == -36.26852
        assert parsed['latest_mag'] == 16.36

    def test_non_integer_id_leaves_atlas_id_none(self):
        message = {
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*ATLAS ID*\nATLAS26jri'},
                ]}
            ]
        }
        parsed = slackbot.parse_bot_message(message)
        assert parsed['atlas_id'] is None

    def test_missing_fields_all_none(self):
        parsed = slackbot.parse_bot_message({'blocks': []})
        assert parsed == {
            'telescope': None, 'related_list': None, 'status': None,
            'atlas_id': None, 'atlas_name': None, 'ra': None, 'dec': None, 'latest_mag': None,
            'note': None,
        }

    def test_real_sample_fixture(self):
        message = load_fixture('slack_sample_bot_message.json')
        parsed = slackbot.parse_bot_message(message)
        assert parsed['ra'] == 208.30919
        assert parsed['dec'] == 0.44793
        assert parsed['latest_mag'] == 16.72
        assert parsed['atlas_id'] == 1135314261002652300
        assert parsed['atlas_name'] == 'ATLAS26jij'
        assert parsed['telescope'] == 'SALT'
        assert parsed['related_list'] == '100Mpc Southern Transients'
        assert parsed['status'] == 'Triggered'
        # Fixture has '*Notes*\nNone' - literal 'None' text normalizes to a real None
        assert parsed['note'] is None

    def test_notes_field_with_real_content_is_kept(self):
        message = {'blocks': [
            {'type': 'section', 'fields': [
                {'type': 'mrkdwn', 'text': '*Notes*\nRe-triggered after fibre issue'},
            ]}
        ]}
        parsed = slackbot.parse_bot_message(message)
        assert parsed['note'] == 'Re-triggered after fibre issue'


class TestParseHumanMessage:
    def test_no_report_tag_is_ignored(self):
        text = 'SALT TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['telescope'] is None
        assert parsed['status'] is None
        assert parsed['atlas_id'] is None

    def test_casual_chat_mentioning_trigger_is_ignored(self):
        text = 'did you catch the salt trigger yesterday? ATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['atlas_id'] is None

    def test_report_salt_trigger(self):
        text = 'REPORT\nSALT TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['telescope'] == 'SALT'
        assert parsed['status'] == 'Triggered'
        assert parsed['atlas_id'] == 1135314261002652300
        assert parsed['note'] is None

    def test_report_salt_observed_with_notes(self):
        text = ('REPORT\nSALT OBSERVED\nATLAS ID: 1135314261002652300\n'
                 'Notes: seeing was poor, may need a re-do')
        parsed = slackbot.parse_human_message(text)
        assert parsed['status'] == 'Observed'
        assert parsed['note'] == 'seeing was poor, may need a re-do'

    def test_report_fail_status(self):
        text = 'REPORT\nSALT FAILED\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['status'] == 'Failed'

    def test_report_mookodi(self):
        text = 'REPORT\nMOOKODI TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['telescope'] == 'Mookodi'

    def test_report_lesedi_synonym_for_mookodi(self):
        text = 'REPORT\nLESEDI TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['telescope'] == 'Mookodi'

    def test_report_missing_status_keyword_is_ignored(self):
        text = 'REPORT\nSALT ATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['status'] is None
        assert parsed['telescope'] is None

    def test_report_missing_telescope_keyword_is_ignored(self):
        text = 'REPORT\nTRIGGERED\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed['status'] == 'Triggered'
        assert parsed['telescope'] is None

    def test_report_short_atlas_id_leaves_atlas_id_none(self, caplog):
        text = 'REPORT\nSALT TRIGGER\nATLAS ID: 113531426100265230'
        with caplog.at_level('ERROR'):
            parsed = slackbot.parse_human_message(text)
        assert parsed['atlas_id'] is None
        assert 'not valid ATLAS ID found' in caplog.text

    def test_report_long_atlas_id_leaves_atlas_id_none(self, caplog):
        text = 'REPORT\nSALT TRIGGER\nATLAS ID: 11353142610026523001'
        with caplog.at_level('ERROR'):
            parsed = slackbot.parse_human_message(text)
        assert parsed['atlas_id'] is None


class TestFindCsvFile:
    def test_finds_csv_among_files(self):
        message = {'files': [{'filetype': 'fits'}, {'filetype': 'csv', 'title': 'x'}]}
        assert slackbot.find_csv_file(message) == {'filetype': 'csv', 'title': 'x'}

    def test_no_files_returns_none(self):
        assert slackbot.find_csv_file({}) is None

    def test_no_csv_among_files_returns_none(self):
        assert slackbot.find_csv_file({'files': [{'filetype': 'fits'}]}) is None

    def test_multiple_csvs_returns_first_and_warns(self, caplog):
        message = {'ts': '123', 'files': [
            {'filetype': 'csv', 'title': 'first'},
            {'filetype': 'csv', 'title': 'second'},
        ]}
        with caplog.at_level('WARNING'):
            csv_file = slackbot.find_csv_file(message)
        assert csv_file == {'filetype': 'csv', 'title': 'first'}
        assert 'only using the first' in caplog.text

    def test_real_sample_fixture(self):
        message = load_fixture('slack_sample_csv_message.json')
        csv_file = slackbot.find_csv_file(message)
        assert csv_file is not None
        assert csv_file['title'] == 'ATLAS26jij (exposure 1/2) spectrum CSV'


class TestParseCsvMessageText:
    def test_parses_id_and_name(self):
        text = '*ATLAS26jij*  ·  ATLAS ID 1135314261002652300  ·  Observed — quicklook products'
        result = slackbot.parse_csv_message_text(text)
        assert result == {'atlas_id': 1135314261002652300, 'atlas_name': 'ATLAS26jij'}

    def test_id_placeholder_name_is_not_kept_as_name(self):
        text = '*id1011551480543323800 (exposure 2/2)*  ·  ATLAS ID 1011551480543323800  ·  Observed — quicklook products'
        result = slackbot.parse_csv_message_text(text)
        assert result == {'atlas_id': 1011551480543323800, 'atlas_name': None}

    def test_unrecognised_text_returns_all_none(self):
        assert slackbot.parse_csv_message_text('some other message') == {'atlas_id': None, 'atlas_name': None}


class TestMessageTimeFromTs:
    def test_converts_to_utc_string(self):
        assert slackbot.message_time_from_ts('1690833945.001900') == '2023-07-31 20:05:45'


class TestFetchNewMessages:
    def test_single_page(self):
        client = MagicMock()
        client.conversations_history.return_value = {
            'messages': [{'ts': '1'}, {'ts': '2'}],
            'response_metadata': {'next_cursor': ''},
        }
        messages = slackbot.fetch_new_messages(client, 'C123', oldest='0')
        assert messages == [{'ts': '1'}, {'ts': '2'}]
        client.conversations_history.assert_called_once_with(channel='C123', limit=200, oldest='0')

    def test_follows_pagination_cursor(self):
        client = MagicMock()
        client.conversations_history.side_effect = [
            {'messages': [{'ts': '1'}], 'response_metadata': {'next_cursor': 'abc'}},
            {'messages': [{'ts': '2'}], 'response_metadata': {'next_cursor': ''}},
        ]
        messages = slackbot.fetch_new_messages(client, 'C123', oldest='0')
        assert messages == [{'ts': '1'}, {'ts': '2'}]
        assert client.conversations_history.call_count == 2
        second_call_kwargs = client.conversations_history.call_args_list[1].kwargs
        assert second_call_kwargs['cursor'] == 'abc'

    def test_no_oldest_omits_it_from_request(self):
        client = MagicMock()
        client.conversations_history.return_value = {
            'messages': [], 'response_metadata': {'next_cursor': ''},
        }
        slackbot.fetch_new_messages(client, 'C123', oldest=None)
        client.conversations_history.assert_called_once_with(channel='C123', limit=200)


class TestProcessMessage:
    def _make_db(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = str(tmp_path / 'test.db')
        conn = sqlite3.connect(db_path)
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'log.sql')
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.close()
        monkeypatch.setattr(db, 'get_connection', lambda path=None: sqlite3.connect(db_path))
        return db_path

    def test_bot_message_without_profile_is_skipped(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)

        client = MagicMock()
        message = {'bot_id': 'B123', 'user': 'U0BM9M40WN8', 'ts': '1690833945.001900', 'upload': True}

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        count = conn.execute('SELECT COUNT(*) FROM slack_messages').fetchone()[0]
        conn.close()
        assert count == 0
        client.users_info.assert_not_called()

    def test_bot_message_logs_parsed_fields(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)

        client = MagicMock()
        message = {
            'bot_id': 'B123',
            'bot_profile': {'name': 'ATLAS SALT Triggers'},
            'ts': '1690833945.001900',
            'text': 'ATLAS Transient SALT requests: 1 new target(s)',
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*ATLAS ID*\n1120650750361606600'},
                    {'type': 'mrkdwn', 'text': '*Status*\nTriggered'},
                    {'type': 'mrkdwn', 'text': '*Trigger source*\nsouth_transients_100mpc'},
                ]}
            ],
        }

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, telescope, related_list, atlas_id, status FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row == ('ATLAS SALT Triggers', 'SALT', 'south_transients_100mpc', 1120650750361606600, 'Triggered')

    def test_human_message_logs_sender_only(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)

        client = MagicMock()
        client.users_info.return_value = {'user': {'real_name': 'Simon de Wet'}}
        message = {'user': 'U456', 'ts': '1690833945.001900', 'text': 'SALT confirms trigger on 2026abc'}

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, telescope, atlas_id FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row == ('Simon de Wet', None, None)

    def test_csv_message_parses_atlas_id_from_text_and_downloads(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)
        spectra_dir = tmp_path / 'spectra'
        monkeypatch.setattr(slackbot, 'SPECTRA_DIR', str(spectra_dir))

        message = load_fixture('slack_sample_csv_message.json')
        client = MagicMock()
        client.token = 'xoxb-fake-token'
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        mock_response = MagicMock()
        mock_response.content = b'wavelength_angs,flux\n4000,1.0\n'
        mock_get = MagicMock(return_value=mock_response)
        monkeypatch.setattr(slackbot.requests, 'get', mock_get)

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, atlas_id, atlas_name, status, note FROM slack_messages '
            "WHERE slack_ts = '1786093308.000100'"
        ).fetchone()
        conn.close()

        assert row[0] == 'Southern Triggers'
        assert row[1] == 1135314261002652300
        assert row[2] == 'ATLAS26jij'
        assert row[3] == 'Spectrum CSV'
        csv_path = row[4]
        assert csv_path == str(spectra_dir / 'ATLAS26jij_1_MKD_20260806.0104.csv')
        assert os.path.exists(csv_path)
        with open(csv_path, 'rb') as f:
            assert f.read() == b'wavelength_angs,flux\n4000,1.0\n'

        mock_get.assert_called_once_with(
            'https://files.slack.com/files-pri/THTTNC3S8-F0BNS8WEAGH/download/atlas26jij_1_mkd_20260806.0104.csv',
            headers={'Authorization': 'Bearer xoxb-fake-token'},
        )
