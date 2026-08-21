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
        assert len(parsed) == 1
        assert parsed[0]['atlas_id'] == 1120650750361606600
        assert parsed[0]['ra'] == 181.71149
        assert parsed[0]['dec'] == -36.26852
        assert parsed[0]['latest_mag'] == 16.36

    def test_non_integer_id_leaves_atlas_id_none(self):
        message = {
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*ATLAS ID*\nATLAS26jri'},
                ]}
            ]
        }
        parsed = slackbot.parse_bot_message(message)
        assert parsed[0]['atlas_id'] is None

    def test_missing_fields_all_none(self):
        parsed = slackbot.parse_bot_message({'blocks': []})
        assert parsed == [{
            'telescope': None, 'related_list': None, 'status': None,
            'atlas_id': None, 'atlas_name': None, 'ra': None, 'dec': None, 'latest_mag': None,
            'note': None,
        }]

    def test_real_sample_fixture(self):
        message = load_fixture('slack_sample_bot_message.json')
        parsed = slackbot.parse_bot_message(message)
        assert len(parsed) == 1
        assert parsed[0]['ra'] == 208.30919
        assert parsed[0]['dec'] == 0.44793
        assert parsed[0]['latest_mag'] == 16.72
        assert parsed[0]['atlas_id'] == 1135314261002652300
        assert parsed[0]['atlas_name'] == 'ATLAS26jij'
        assert parsed[0]['telescope'] == 'SALT'
        assert parsed[0]['related_list'] == '100Mpc Southern Transients'
        assert parsed[0]['status'] == 'Triggered'
        # Fixture has '*Notes*\nNone' - literal 'None' text normalizes to a real None
        assert parsed[0]['note'] is None

    def test_notes_field_with_real_content_is_kept(self):
        message = {'blocks': [
            {'type': 'section', 'fields': [
                {'type': 'mrkdwn', 'text': '*Notes*\nRe-triggered after fibre issue'},
            ]}
        ]}
        parsed = slackbot.parse_bot_message(message)
        assert parsed[0]['note'] == 'Re-triggered after fibre issue'

    def test_two_targets_in_one_message_are_both_parsed(self):
        # Claude wrote this for issue #37 (2026-08-14), fixture is a real captured
        # message where the bug lost the first of two SALT trigger targets.
        message = load_fixture('slack_sample_bot_multi_target_message.json')
        parsed = slackbot.parse_bot_message(message)
        assert len(parsed) == 2
        assert parsed[0]['atlas_id'] == 1022628271010936300
        assert parsed[0]['telescope'] == 'SALT'
        assert parsed[0]['status'] == 'Triggered'
        assert parsed[1]['atlas_id'] == 1020547660051719200
        assert parsed[1]['telescope'] == 'SALT'
        assert parsed[1]['status'] == 'Triggered'


class TestParseHumanMessage:
    def test_no_report_tag_is_ignored(self):
        text = 'SALT TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert len(parsed) == 1
        assert parsed[0]['telescope'] is None
        assert parsed[0]['status'] is None
        assert parsed[0]['atlas_id'] is None

    def test_casual_chat_mentioning_trigger_is_ignored(self):
        text = 'did you catch the salt trigger yesterday? ATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert len(parsed) == 1
        assert parsed[0]['atlas_id'] is None

    def test_report_salt_trigger(self):
        text = 'REPORT\nSALT TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert len(parsed) == 1
        assert parsed[0]['telescope'] == 'SALT'
        assert parsed[0]['status'] == 'Triggered'
        assert parsed[0]['atlas_id'] == 1135314261002652300
        assert parsed[0]['note'] is None

    def test_report_salt_observed_with_notes(self):
        text = ('REPORT\nSALT OBSERVED\nATLAS ID: 1135314261002652300\n'
                 'Notes: seeing was poor, may need a re-do')
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['status'] == 'Observed'
        assert parsed[0]['note'] == 'seeing was poor, may need a re-do'

    def test_report_status_keyword_typo_in_notes_is_ignored(self):
        # Claude wrote this for issue #41 (2026-08-17): "trogger" in the
        # Notes text used to be matched as "trigger" because keywords were
        # searched across the whole block instead of stopping at "Notes:".
        text = ('REPORT\nSALT OBSERVED\nATLAS ID: 1201510860524316900\n'
                 'Notes: data obtained on second night after trogger.')
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['status'] == 'Observed'
        assert parsed[0]['note'] == 'data obtained on second night after trogger.'

    def test_report_fail_status(self):
        text = 'REPORT\nSALT FAILED\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['status'] == 'Failed'

    def test_report_mookodi(self):
        text = 'REPORT\nMOOKODI TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['telescope'] == 'Mookodi'

    def test_report_lesedi_synonym_for_mookodi(self):
        text = 'REPORT\nLESEDI TRIGGER\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['telescope'] == 'Mookodi'

    def test_report_missing_status_keyword_is_ignored(self):
        text = 'REPORT\nSALT ATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['status'] is None
        assert parsed[0]['telescope'] is None

    def test_report_missing_telescope_keyword_is_ignored(self):
        text = 'REPORT\nTRIGGERED\nATLAS ID: 1135314261002652300'
        parsed = slackbot.parse_human_message(text)
        assert parsed[0]['status'] == 'Triggered'
        assert parsed[0]['telescope'] is None

    def test_report_short_atlas_id_leaves_atlas_id_none(self, caplog):
        text = 'REPORT\nSALT TRIGGER\nATLAS ID: 113531426100265230'
        with caplog.at_level('ERROR'):
            parsed = slackbot.parse_human_message(text)
        assert parsed[0]['atlas_id'] is None
        assert 'not valid ATLAS ID found' in caplog.text

    def test_report_long_atlas_id_leaves_atlas_id_none(self, caplog):
        text = 'REPORT\nSALT TRIGGER\nATLAS ID: 11353142610026523001'
        with caplog.at_level('ERROR'):
            parsed = slackbot.parse_human_message(text)
        assert parsed[0]['atlas_id'] is None

    def test_two_reports_in_one_message_are_both_parsed(self):
        text = ('REPORT\nSALT TRIGGER\nATLAS ID: 1022628271010936300\n\n'
                 'REPORT\nSALT TRIGGER\nATLAS ID: 1020547660051719200')
        parsed = slackbot.parse_human_message(text)
        assert len(parsed) == 2
        assert parsed[0]['telescope'] == 'SALT'
        assert parsed[0]['status'] == 'Triggered'
        assert parsed[0]['atlas_id'] == 1022628271010936300
        assert parsed[1]['telescope'] == 'SALT'
        assert parsed[1]['status'] == 'Triggered'
        assert parsed[1]['atlas_id'] == 1020547660051719200

    def test_two_reports_different_telescopes_and_status(self):
        text = ('REPORT\nSALT TRIGGER\nATLAS ID: 1022628271010936300\n\n'
                 'REPORT\nMOOKODI OBSERVED\nATLAS ID: 1020547660051719200\n'
                 'Notes: clean detection')
        parsed = slackbot.parse_human_message(text)
        assert len(parsed) == 2
        assert parsed[0]['telescope'] == 'SALT'
        assert parsed[0]['status'] == 'Triggered'
        assert parsed[1]['telescope'] == 'Mookodi'
        assert parsed[1]['status'] == 'Observed'
        assert parsed[1]['note'] == 'clean detection'


class TestFindSpectrumFile:
    def test_finds_txt_among_files(self):
        message = {'files': [{'filetype': 'fits'}, {'filetype': 'text', 'title': 'x'}]}
        assert slackbot.find_spectrum_file(message) == {'filetype': 'text', 'title': 'x'}

    def test_no_files_returns_none(self):
        assert slackbot.find_spectrum_file({}) is None

    def test_no_spectrum_file_among_files_returns_none(self):
        assert slackbot.find_spectrum_file({'files': [{'filetype': 'fits'}]}) is None

    # Claude wrote this for issue #44 (2026-08-21): csv is no longer picked up
    # at all - H decided not to keep it as a fallback, only txt is used now.
    def test_csv_only_files_returns_none(self):
        message = {'files': [{'filetype': 'csv', 'title': 'x'}]}
        assert slackbot.find_spectrum_file(message) is None

    def test_multiple_txts_returns_first_and_warns(self, caplog):
        message = {'ts': '123', 'files': [
            {'filetype': 'text', 'title': 'first'},
            {'filetype': 'text', 'title': 'second'},
        ]}
        with caplog.at_level('WARNING'):
            spectrum_file = slackbot.find_spectrum_file(message)
        assert spectrum_file == {'filetype': 'text', 'title': 'first'}
        assert 'only using the first' in caplog.text

    def test_real_csv_only_sample_fixture_returns_none(self):
        message = load_fixture('slack_sample_csv_message.json')
        assert slackbot.find_spectrum_file(message) is None

    def test_real_txt_and_csv_sample_fixture_picks_txt(self):
        message = load_fixture('slack_sample_txt_message.json')
        spectrum_file = slackbot.find_spectrum_file(message)
        assert spectrum_file is not None
        assert spectrum_file['filetype'] == 'text'
        assert spectrum_file['name'] == 'ATLAS26jwv_MKD_20260820.0113.txt'


class TestParseSpectrumMessageText:
    def test_parses_id_and_name(self):
        text = '*ATLAS26jij*  ·  ATLAS ID 1135314261002652300  ·  Observed — quicklook products'
        result = slackbot.parse_spectrum_message_text(text)
        assert result == {'atlas_id': 1135314261002652300, 'atlas_name': 'ATLAS26jij'}

    def test_id_placeholder_name_is_not_kept_as_name(self):
        text = '*id1011551480543323800 (exposure 2/2)*  ·  ATLAS ID 1011551480543323800  ·  Observed — quicklook products'
        result = slackbot.parse_spectrum_message_text(text)
        assert result == {'atlas_id': 1011551480543323800, 'atlas_name': None}

    def test_unrecognised_text_returns_all_none(self):
        assert slackbot.parse_spectrum_message_text('some other message') == {'atlas_id': None, 'atlas_name': None}


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

    def test_bot_message_without_profile_is_logged_with_null_status(self, monkeypatch, tmp_path):
        # Claude wrote this for issue #38 (2026-08-14): skipped messages must
        # still get a row, otherwise the polling cursor (MAX(slack_ts)) never
        # advances past them and the bot re-fetches them forever.
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)

        client = MagicMock()
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        message = {'bot_id': 'B123', 'user': 'U0BM9M40WN8', 'ts': '1690833945.001900', 'upload': True}

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT slack_ts, status, note FROM slack_messages'
        ).fetchone()
        conn.close()
        assert row[0] == '1690833945.001900'
        assert row[1] is None
        assert row[2] is not None and 'image upload' in row[2]
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

    def test_bot_message_with_two_targets_logs_two_rows(self, monkeypatch, tmp_path):
        # Claude wrote this for issue #37 (2026-08-14), real captured message
        # where "2 new target(s)" used to collapse into a single db row.
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)

        client = MagicMock()
        message = load_fixture('slack_sample_bot_multi_target_message.json')

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            'SELECT atlas_id, telescope, status FROM slack_messages ORDER BY atlas_id'
        ).fetchall()
        conn.close()
        assert rows == [
            (1020547660051719200, 'SALT', 'Triggered'),
            (1022628271010936300, 'SALT', 'Triggered'),
        ]

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

    def test_human_message_with_two_reports_logs_two_rows(self, monkeypatch, tmp_path):
        # Claude wrote this for issue #37 (2026-08-14): a single Slack message
        # batching two REPORT blocks must produce two rows, not one.
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)

        client = MagicMock()
        client.users_info.return_value = {'user': {'real_name': 'Simon de Wet'}}
        message = {
            'user': 'U456',
            'ts': '1690833945.001900',
            'text': ('REPORT\nSALT TRIGGER\nATLAS ID: 1022628271010936300\n\n'
                      'REPORT\nSALT TRIGGER\nATLAS ID: 1020547660051719200'),
        }

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            'SELECT slack_ts, atlas_id, status FROM slack_messages ORDER BY atlas_id'
        ).fetchall()
        conn.close()
        assert rows == [
            ('1690833945.001900', 1020547660051719200, 'Triggered'),
            ('1690833945.001900', 1022628271010936300, 'Triggered'),
        ]

    # Claude wrote this for issue #44 (2026-08-21): csv is no longer treated
    # as a spectrum file at all, so a csv-only message falls through to the
    # same "ignore" path as any other file-less/picture bot upload.
    def test_csv_only_message_is_ignored_not_downloaded(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)
        spectra_dir = tmp_path / 'spectra'
        monkeypatch.setattr(slackbot, 'SPECTRA_DIR', str(spectra_dir))

        message = load_fixture('slack_sample_csv_message.json')
        client = MagicMock()
        client.token = 'xoxb-fake-token'
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        mock_get = MagicMock()
        monkeypatch.setattr(slackbot.requests, 'get', mock_get)

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, atlas_id, status, note FROM slack_messages '
            "WHERE slack_ts = '1786093308.000100'"
        ).fetchone()
        conn.close()

        assert row[0] == 'Southern Triggers'
        assert row[1] is None
        assert row[2] is None
        assert row[3] == 'Ignore: likely image upload'
        mock_get.assert_not_called()
        assert not os.path.exists(spectra_dir)

    # Claude wrote this for issue #44 (2026-08-21): real message fixture that
    # carries both a txt and a csv - the txt must be the one downloaded/logged.
    def test_txt_and_csv_message_prefers_txt_and_downloads(self, monkeypatch, tmp_path):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)
        spectra_dir = tmp_path / 'spectra'
        monkeypatch.setattr(slackbot, 'SPECTRA_DIR', str(spectra_dir))

        message = load_fixture('slack_sample_txt_message.json')
        client = MagicMock()
        client.token = 'xoxb-fake-token'
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        mock_response = MagicMock()
        mock_response.content = b'# wavelength_angstrom normalised_flux\n4090.14 0.729183\n'
        mock_get = MagicMock(return_value=mock_response)
        monkeypatch.setattr(slackbot.requests, 'get', mock_get)

        slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT sender_name, atlas_id, atlas_name, status, note FROM slack_messages '
            "WHERE slack_ts = '1787299228.105739'"
        ).fetchone()
        conn.close()

        assert row[0] == 'Southern Triggers'
        assert row[1] == 1020547660051719200
        assert row[2] == 'ATLAS26jwv'
        assert row[3] == 'Spectrum TXT'
        txt_path = row[4]
        assert txt_path == str(spectra_dir / 'ATLAS26jwv_MKD_20260820.0113.txt')
        assert os.path.exists(txt_path)

        mock_get.assert_called_once_with(
            'https://files.slack.com/files-pri/THTTNC3S8-F0BRU21LGJV/download/atlas26jwv_mkd_20260820.0113.txt',
            headers={'Authorization': 'Bearer xoxb-fake-token'},
        )

    # Claude wrote this for the logging review (2026-08-14): H couldn't tell
    # from the logs alone whether a spectrum download had actually succeeded.
    # Claude switched this to the txt fixture for issue #44 (2026-08-21) since
    # csv is no longer downloaded at all.
    def test_txt_download_success_is_logged(self, monkeypatch, tmp_path, caplog):
        db_path = self._make_db(monkeypatch, tmp_path)
        spectra_dir = tmp_path / 'spectra'
        monkeypatch.setattr(slackbot, 'SPECTRA_DIR', str(spectra_dir))

        message = load_fixture('slack_sample_txt_message.json')
        client = MagicMock()
        client.token = 'xoxb-fake-token'
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        mock_response = MagicMock()
        mock_response.content = b'# wavelength_angstrom normalised_flux\n4090.14 0.729183\n'
        monkeypatch.setattr(slackbot.requests, 'get', MagicMock(return_value=mock_response))

        with caplog.at_level('INFO'):
            slackbot.process_message(message, client, {})

        assert 'Saved spectrum file' in caplog.text
        assert 'ATLAS26jwv_MKD_20260820.0113.txt' in caplog.text

    # Claude wrote this for issue #39 (2026-08-14): a failed spectrum download
    # must still leave a row behind (status=None, error in note), both so
    # the failure is visible in the db and so the polling cursor advances
    # past this message instead of re-fetching it forever (see #38).
    # Claude switched this to the txt fixture for issue #44 (2026-08-21) since
    # csv is no longer downloaded at all.
    def test_txt_download_failure_logs_error_row_instead_of_dropping_silently(self, monkeypatch, tmp_path, caplog):
        import sqlite3
        db_path = self._make_db(monkeypatch, tmp_path)
        spectra_dir = tmp_path / 'spectra'
        monkeypatch.setattr(slackbot, 'SPECTRA_DIR', str(spectra_dir))

        message = load_fixture('slack_sample_txt_message.json')
        client = MagicMock()
        client.token = 'xoxb-fake-token'
        client.bots_info.return_value = {'bot': {'name': 'Southern Triggers'}}
        mock_get = MagicMock(side_effect=OSError('permission denied'))
        monkeypatch.setattr(slackbot.requests, 'get', mock_get)

        with caplog.at_level('ERROR'):
            slackbot.process_message(message, client, {})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT status, note FROM slack_messages WHERE slack_ts = ?',
            ('1787299228.105739',),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] is None
        assert 'permission denied' in row[1]
        assert 'Failed to process Slack message' in caplog.text
