import json
import logging
from datetime import datetime, timezone
from slack_sdk import WebClient
import atlas_sao.db as db
from atlas_sao.slack_config import load_slack_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# ############################# #
# ####  PARSER UTILITIES   #### #  
# ############################# #

def resolve_sender(message: dict, 
                   client, 
                   cache: dict) -> tuple:
    """Figure out who sent the message"""
    if 'bot_id' in message:
        sender_id = message['bot_id']
        sender_name = message['bot_profile']['name']
    else:
        sender_id = message['user']
        # When a human sends a message we have their user ID but not their name 
        # that is because human messages don't carry the user profile like the bots
        # carry a bor profile. To avoid too many API calls we CACHE the info
        # We don't make a dictionary with the user id -> user name relation
        # because that's probably not a great thing to put on a public GH repo ;) 
        if sender_id not in cache:
            info = client.users_info(user=sender_id)
            cache[sender_id] = info['user']['real_name']
        sender_name = cache[sender_id]

    return sender_id, sender_name


# ############################# #
# ####        PARSER       #### #  
# ############################# #

def parse_blocks_fields(blocks: list) -> dict:
    """Parsers the BLOCKS in a given slack message
    That is a techincal term, a specific field name 
    (see tests/fixtures slack_sample_bot_message.json)

    Returns
    -------
    Dictionary of 
    """
    fields = {}

    # NOTE: This is extremly tied to how nic writes his messages
    for block in blocks:
        if block.get('type') != 'section':
            # we ignore e.g. dividers, headers
            continue
        for field in block.get('fields', []):
            # Fields is a list of small dictionaries that contain each a line of text
            # this is where we find the RA Dec etc... 
            text = field.get('text', '')
            # NOTE: This if statements looks for highlighted text that looks like labels
            # again, very specific to how Nic formats.
            if text.startswith('*') and '\n' in text:
                # His format is like so: "*RA / Dec*\n181.71149, -36.26852"
                # We have a BOLD text, then a new line, then the DATA
                # this partition splits the string into 3 components
                # 1. *RA / Dec* (-> label)
                # 2. \n (-> _ )
                # 3. 181.71149, -36.26852 (-> value)
                label, _, value = text.partition('\n')
                # This then creates the a new field in the dictionary 
                # "RA / Dec": "181.71149, -36.26852"
                fields[label.strip('*').strip()] = value.strip()

    # after we have looped over the whole block we will have:
    # RA /Dec, Max Track, Disc. mag / date, Latest, Crossmatch
    # We won't need all of them but at least it's an easy dictionary and
    # formating is removed. 
    return fields


def parse_telescope_from_text(text: str) -> str | None:
    """# Claude wrote this for the Nic bot format change (2026-08-06)"""
    text_lower = text.lower()
    if 'salt' in text_lower:
        return 'SALT'
    if 'mookodi' in text_lower:
        return 'Mookodi'
    return None


def parse_bot_message(message: dict) -> dict:
    """Parses a single message from a bot

    Returns
    -------
    dictionary with keys:
    - 'telescope','related_list','atlas_id', 'ra','dec','latest_mag'
    """
    fields = parse_blocks_fields(message.get('blocks', []))

    parsed = {
        'telescope': parse_telescope_from_text(message.get('text', '')),
        'related_list': fields.get('Trigger source'),
        'status': fields.get('Status'),
        'atlas_id': None,
        'ra': None,
        'dec': None,
        'latest_mag': None,
    }

    raw_id = fields.get('ATLAS ID')
    if raw_id is not None:
        try:
            parsed['atlas_id'] = int(raw_id.strip())
        except ValueError:
            logging.warning(f"Slack bot message 'ATLAS ID' field not an integer, skipping atlas_id: {raw_id!r}")

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


# ################# #
# #### POLLING #### #
# ################# #

def message_time_from_ts(ts: str) -> str:
    """Slack ts (timestamp) in Unix Epoch in Seconds - converts to UTC date time"""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def fetch_new_messages(client,
                       channel_id: str,
                       oldest: str | None,
                       n: int = 200) -> list:
    """Polls for new messages in the channel
    
    Parameters
    -----------
    client: slack_sdk.WebClient
       Slack client
    channel_id: str
       The Channel Id
    oldest: str
        The last message we polled (slack ts)
    n: int
       Max number of messages to look at in a while loop
    """
    messages = []
    cursor = None
    while True:
        # Only polling n messages at most in a single loop
        kwargs = {'channel': channel_id, 'limit': n}
        if oldest:
            kwargs['oldest'] = oldest
        if cursor:
            # If we end up with a queue longer than n 
            # we will get a cursor from the metadata to keep our place 
            # and keep going in the next loop
            kwargs['cursor'] = cursor

        # Get the response from the client
        resp = client.conversations_history(**kwargs)
        messages.extend(resp['messages'])
        # Guessing slack gives us the next_crusor in the metadata so we
        # don't have to actually read the contents of the message to find latest slack_ts
        cursor = resp.get('response_metadata', {}).get('next_cursor')

        # If we didn't get a cursor we are finished! We break from the loop
        if not cursor:
            break
    return messages


def process_message(message: dict,
                    client,
                    sender_cache: dict) -> None:
    """Fully processes a single slack message
    """
    if 'bot_id' in message and 'bot_profile' not in message:
        # Claude wrote this for the bot file-upload skip (2026-08-06)
        logging.info(f"Skipping bot message with no bot_profile (likely a file upload), ts={message.get('ts')}")
        return

    # 1. Who sent us the message? Bot or User?
    sender_id, sender_name = resolve_sender(message, client, sender_cache)

    # 2. Get the "parsed" dictionary with fields of interest
    if 'bot_id' in message:
        parsed = parse_bot_message(message)
        # If it's a bot message we use a specific parser because the json looks different
        # case in point: there is no top level 'text' field to read like in the human
        # messages (see else statement)
        raw_text = None
        raw_blocks = json.dumps(message.get('blocks', []))
        # These raw locks will get parsed later in the function. They include header, dividers,
        # context, and cruicial section blocks where our text resides
    else:
        # if it wasn't a bot, it was a human
        # We initialize the parsed dictionary with empty values
        # because we don't yet have the parser, 
        parsed = {'telescope': None,
                  'related_list': None,
                  'status': None,
                  'atlas_id': None,
                  'ra': None,
                  'dec': None,
                  'latest_mag': None}
        
        raw_text = message.get('text')
        raw_blocks = None

    # 3 - Update the slack_messages table
    db.log_slack_message(
        slack_ts=message['ts'],
        sender_id=sender_id,
        sender_name=sender_name,
        telescope=parsed['telescope'],
        related_list=parsed['related_list'],
        raw_text=raw_text,
        raw_blocks=raw_blocks,
        atlas_id=parsed['atlas_id'],
        ra=parsed['ra'],
        dec=parsed['dec'],
        latest_mag=parsed['latest_mag'],
        status=parsed['status'],
        message_time=message_time_from_ts(message['ts']),
    )
    return 


if __name__ == "__main__":
    # ############ #
    # 0. SET UP
    # ############ #

    # 0.1 Load the slack token for relevant bot and channel of interest
    #     No params so hitting default values in slack_config_MINE.yaml
    config = load_slack_config()
    logging.info(f"Found and loaded config")

    # 0.2 Instantiate our slack web client (not atlasapiclient)
    client = WebClient(token=config['bot_token'])

    # ############ #
    # 1. POLL
    # ############ #
    
    # 1.1 Get the slack timestamp for the last message we received
    #     That is also our cursor?
    oldest = db.get_last_slack_ts()
    # 1.2 Poll the last n messages in our channel
    messages = fetch_new_messages(client, config['channel_id'], oldest, n=200)
    logging.info(f"Fetched {len(messages)} new Slack messages.")

    # 1.3 Instanciate empty sender_cache dict. Will be filled 
    #     With key value pairs that connect a sender id to a sender name
    #     to avoid duplicate API calls (as human messages show sender id but NOT name
    #     we need to do at least one API call to get that info)
    sender_cache = {}

    # 1.4 Looping over each message to process them: parse + add rows to log db (.slack_messages)
    for message in messages:
        try:
            process_message(message, client, sender_cache)
        except Exception:
            logging.exception(f"Failed to process Slack message ts={message.get('ts')}")
