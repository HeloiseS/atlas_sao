import os
import yaml

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), 'config_files', 'slack_config_MINE.yaml'
)


def load_slack_config(config_path: str = None, bot_name: str = "el01z") -> dict:
    """Loads the slack config for the right bot
    
    Note
    -----
    At present (2026-08-05) we only use the one slack bot (el01z) but 
    adding the option to load other bot configs to future proof.

    The environment variables should have THE CORRECT NAME expected by
    this function: 'el0iz_CONFIG_SLACK'or 'st3ph3n_CONFIG_SLACK'
    (Add new bot and env variable if you make a new one)
    """
    if config_path is None and bot_name=="el01z":
        # can define path to the slack config file using env variable
        config_path = os.environ.get('el0iz_CONFIG_SLACK', DEFAULT_CONFIG_PATH)
    elif config_path is None and bot_name=="st3ph3n":
        # can define path to the slack config file using env variable
        config_path = os.environ.get('st3ph3n_CONFIG_SLACK', DEFAULT_CONFIG_PATH)
    # Add new bot here if needed

    with open(config_path) as f:
        return yaml.safe_load(f)
