from unittest.mock import MagicMock
import atlas_sao.slackbot as slackbot


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
