import json
import os
from unittest.mock import MagicMock
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


class TestResolveTelescopeAndList:
    def test_uses_parsed_fields_when_present(self):
        result = slackbot.resolve_telescope_and_list(
            'B123', {'telescope': 'SALT', 'related_list': 'south_transients_100mpc'}, {}
        )
        assert result == ('SALT', 'south_transients_100mpc')

    def test_falls_back_to_sender_lookup(self):
        lookup = {'B123': {'telescope': 'SALT', 'related_list': 'south_transients_100mpc'}}
        result = slackbot.resolve_telescope_and_list('B123', {}, lookup)
        assert result == ('SALT', 'south_transients_100mpc')

    def test_unknown_sender_returns_none(self):
        result = slackbot.resolve_telescope_and_list('B999', {}, {})
        assert result == (None, None)


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


class TestParseBotMessage:
    def test_parses_id_ra_dec_latest_mag(self):
        message = {
            'bot_id': 'B123',
            'blocks': [
                {'type': 'section', 'fields': [
                    {'type': 'mrkdwn', 'text': '*id*\n1120650750361606600'},
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
                    {'type': 'mrkdwn', 'text': '*id*\nATLAS26jri'},
                ]}
            ]
        }
        parsed = slackbot.parse_bot_message(message)
        assert parsed['atlas_id'] is None

    def test_missing_fields_all_none(self):
        parsed = slackbot.parse_bot_message({'blocks': []})
        assert parsed == {
            'telescope': None, 'related_list': None,
            'atlas_id': None, 'ra': None, 'dec': None, 'latest_mag': None,
        }

    def test_real_sample_fixture(self):
        message = load_fixture('slack_sample_bot_message.json')
        parsed = slackbot.parse_bot_message(message)
        assert parsed['ra'] == 181.71149
        assert parsed['dec'] == -36.26852
        assert parsed['latest_mag'] == 16.36
        assert parsed['atlas_id'] is None
        assert parsed['telescope'] is None
        assert parsed['related_list'] is None
