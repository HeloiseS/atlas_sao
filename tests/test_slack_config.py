import atlas_sao.slack_config as slack_config


def test_loads_yaml_contents(tmp_path):
    config_file = tmp_path / 'slack_config_test.yaml'
    config_file.write_text('bot_token: "xoxb-test"\nchannel_id: "C123"\n')
    config = slack_config.load_slack_config(str(config_file))
    assert config['bot_token'] == 'xoxb-test'
    assert config['channel_id'] == 'C123'


def test_env_var_override_el01z(tmp_path, monkeypatch):
    config_file = tmp_path / 'slack_config_test.yaml'
    config_file.write_text('bot_token: "xoxb-test"\nchannel_id: "C123"\n')
    monkeypatch.setenv('el0iz_CONFIG_SLACK', str(config_file))
    config = slack_config.load_slack_config()
    assert config['bot_token'] == 'xoxb-test'


def test_env_var_override_st3ph3n(tmp_path, monkeypatch):
    config_file = tmp_path / 'slack_config_test.yaml'
    config_file.write_text('bot_token: "xoxb-other"\nchannel_id: "C456"\n')
    monkeypatch.setenv('st3ph3n_CONFIG_SLACK', str(config_file))
    config = slack_config.load_slack_config(bot_name='st3ph3n')
    assert config['bot_token'] == 'xoxb-other'
