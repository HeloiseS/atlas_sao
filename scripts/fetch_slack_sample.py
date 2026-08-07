import json
from slack_sdk import WebClient
from atlas_sao.slack_config import load_slack_config

config = load_slack_config()
client = WebClient(token=config['bot_token'])
resp = client.conversations_history(channel=config['channel_id'], limit=20)
print(json.dumps(resp['messages'], indent=2))
