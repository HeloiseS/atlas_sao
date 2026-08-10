import logging
import os
import re
from datetime import datetime, timezone
import requests
from slack_sdk import WebClient
import atlas_sao.db as db
from atlas_sao.slack_config import load_slack_config

SPECTRA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'spectra')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

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


# ############################# #
# ####  PARSER UTILITIES   #### #  
# ############################# #

def resolve_sender(message: dict,
                   client,
                   cache: dict) -> tuple:
    """Figure out who sent the message"""
    if 'bot_id' in message:
        sender_id = message['bot_id']
        if 'bot_profile' in message:
            # A typical bot message also has the bot profile info
            sender_name = message['bot_profile']['name']
        else:
            # However when the bot sends just file like the csv spectra
            # it doesn't then we have to use the api to get the 
            # bot name from its ID.
            if sender_id not in cache:
                info = client.bots_info(bot=sender_id)
                cache[sender_id] = info['bot']['name']
            sender_name = cache[sender_id]
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


def parse_blocks_fields(blocks: list) -> dict:
    """Parses the BLOCKS in a given slack message
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


def parse_object_name(blocks: list) -> str | None:
    """Claude wrote this for spectrum CSV correlation (2026-08-07)

    Pulls the ATLAS object name (e.g. 'ATLAS26jij') out of the section
    block's own heading text, e.g. '*ATLAS26jij (exposure 2/2)*  ·  ...'
    or '*ATLAS26jij*  ·  SN  ·  ...'. This is separate from parse_blocks_fields
    because the name lives in the section's 'text', not its 'fields' list.
    """
    for block in blocks:
        if block.get('type') != 'section':
            continue
        text = block.get('text', {}).get('text', '')
        match = re.match(r'\*([A-Za-z0-9]+)', text)
        if match:
            return match.group(1)
    return None


# ############################# #
# ##  HUMAN TEXT MESSAGE   #### #
# ############################# #

def parse_human_message(text: str) -> dict:
    """Parsing the human messages with a given report formatting
    This is because SALT triggers are human initiated so Simon or 
    someone else will feedback directly to the bot channel when a trigger
    occurs and is successful.
    """
    parsed = {
        'telescope': None,
        'related_list': None,
        'status': None,
        'atlas_id': None,
        'atlas_name': None,
        'ra': None,
        'dec': None,
        'latest_mag': None,
        'note': None,
    }

    # We look for the REPORT keyword at the START of the message
    # otherwise ignore. This is to avoid makring a salt trigger
    # in the db from casual chat in the comments or threads 
    # that may sprout in the slack bot channel. 
    if not re.search(r'^\s*REPORT\s*$', text, re.IGNORECASE | re.MULTILINE):
        return parsed

    # Just in case typos and we get a mixture of cases

    text_lower = text.lower()
    if 'trigger' in text_lower:
        parsed['status'] = 'Triggered'
    elif 'observed' in text_lower:
        parsed['status'] = 'Observed'
    elif 'fail' in text_lower:
        parsed['status'] = 'Failed'
    else:
        return parsed

    if 'salt' in text_lower:
        parsed['telescope'] = 'SALT'
    elif 'mookodi' in text_lower or 'lesedi' in text_lower:
        parsed['telescope'] = 'Mookodi'
    else:
        return parsed

    # Here the brackets are doing a lot of work. 
    # If I have (\d{19})?!\d, regex would see first 
    # (\d{19})? which means "match 1 or 0 of the syntax in these brackets (19 digits here)"
    # but (? means that this group in the brackets is special. What kinda special 
    # depends on the next character. ! after (? means we're doing a negative lookahead
    # we are looking at the next character and trying to NOT match the pattern
    # here the pattern is \d, a digit. 
    # overall we and ATLAS ID: -> SPACE -> 19 digits -> ANYTHING BUT A DIGIT 
    # So we're making sure we have 19 digits in our atlas ID, no more no less. 
    id_match = re.search(r'ATLAS ID:\s*(\d{19})(?!\d)', text, re.IGNORECASE)
    if id_match is None:
        logging.error("Human REPORT detected but not valid ATLAS ID found. " \
        "Either it was not provided or it was not 19 digits long")
        return parsed

    parsed['atlas_id'] = int(id_match.group(1))

    note_match = re.search(r'Notes:\s*(.+)', text, re.IGNORECASE)
    if note_match:
        parsed['note'] = note_match.group(1).strip()

    return parsed


# ############################# #
# ####   BOT TEXT MESSAGE  #### #
# ############################# #

def parse_bot_message(message: dict) -> dict:
    """Parses a single message from a bot

    Returns
    -------
    dictionary with keys:
    - 'telescope','related_list','atlas_id','atlas_name','ra','dec','latest_mag','note'
    """
    fields = parse_blocks_fields(message.get('blocks', []))

    parsed = {
        'telescope': parse_telescope_from_text(message.get('text', '')),
        'related_list': fields.get('Trigger source'),
        'status': fields.get('Status'),
        'atlas_id': None,
        'atlas_name': parse_object_name(message.get('blocks', [])),
        'ra': None,
        'dec': None,
        'latest_mag': None,
        # Claude wrote this for the note column (2026-08-07) and HFS read and approved. 
        # Nic's bot writes the literal text 'None' when there's nothing to say,
        # normalized to a real None/NULL here rather than stored as that string.
        'note': fields.get('Notes') if fields.get('Notes') not in (None, 'None') else None,
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


# ############################# #
# ## PARSE CSV SPECTRA FILES ## #  
# ############################# #

def find_csv_file(message: dict) -> dict | None:
    """
    Gets the file sub-dictionary (under "files" list in the JSON) if it is a csv

    Note
    ----
    If there are more than one csv in a message we only return the first one and 
    log a warning so i can tell Nic there is a problem. 
    """
    csv_files = [f for f in message.get('files', []) if f.get('filetype') == 'csv']
    if len(csv_files) > 1:
        logging.warning(f"Message has {len(csv_files)} csv files, only using the first: ts={message.get('ts')}")
    return csv_files[0] if csv_files else None




def parse_csv_message_text(text: str) -> dict:
    """Extract the atlas id and atlas name from the messages that contain the
    spectra files. 

    Note
    -----
    There is a little subtely here because the ATLAS name in the title
    is not always the atlas name. If the name doesn't exist it gets replaced by the id

    Returns
    -------
    dict with keys 'atlas_id' (int or None) and 'atlas_name' (str or None)
    """
    result = {'atlas_id': None, 'atlas_name': None}

    # magic reg exc to find the ATLAS ID
    # the brackets () are the capture group => what comes out from
    # the .group()
    #  ATLAS ID + any numer of spaces + any number of digits 
    id_match = re.search(r'ATLAS ID\s+(\d+)', text)
    if id_match:
        result['atlas_id'] = int(id_match.group(1))

    # magic reg ex to find names like ATLAS26jli
    # Any numbre of characters, each cna be any upper case, lower case or number
    # note that in ASCII upper and lower case are not continuous, there is 
    # punctuation in between! So although A-z is valid, it includes things like ! []
    name_match = re.match(r'\*([A-Za-z0-9]+)', text)
    if name_match:
        candidate = name_match.group(1)
        if candidate != f'id{result["atlas_id"]}':
            # Checking that we don't have idATLAS_ID 
            # in place of the name (that's why we find ATLAS ID first!)
            result['atlas_name'] = candidate

    return result



# ################ #
# ## PROCESSING ## #  
# ################ #

def download_csv_file(url: str, token: str, dest_path: str) -> None:
    """Slack incantation to downlaod the files
    """

    # The csv file is located at some slack URL but it isn't public
    # it's in a url_private_download location. So we need to do 
    # a special kind of Auth operation using our bot token. 
    resp = requests.get(url, headers={'Authorization': f'Bearer {token}'})
    resp.raise_for_status()

    # Create destination repository if does not exists 
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    with open(dest_path, 'wb') as f:
        # resp.content is the raw bytes which we can write straight to storage
        f.write(resp.content)
        

def process_csv_message(message: dict,
                        csv_file: dict,
                        sender_id: str,
                        sender_name: str,
                        client) -> None:
    """Processes the messages that contain csv files -> spectra. 
    """
    # Get the time of the messages
    message_time = message_time_from_ts(message['ts'])
    # ATLAS ID in the text of the message. Sometimes it will also contain the name. 
    # NOTE: Hopefully I can fix nick's code that the ATLAS name will be superfluous
    parsed = parse_csv_message_text(message.get('text', ''))
    atlas_id = parsed['atlas_id']
    atlas_name = parsed['atlas_name']

    csv_path = None

    if atlas_id is None:
        # I made the decision that if the ATLAS ID is not there we don't download
        # I've said countless time the ATLAS ID is crucial, so we are not
        # handling this gracefully. 
        logging.warning(f"Could not parse ATLAS ID from csv message text, skipping download: ts={message.get('ts')} text={message.get('text', '')!r}")
    else:
        csv_path = os.path.join(SPECTRA_DIR, csv_file['name'])
        download_csv_file(csv_file['url_private_download'], client.token, csv_path)

    # Add a row to our slack messages with status Spectrum CSV
    # Save the csv_path to the "Note" column 
    db.log_slack_message(
        slack_ts=message['ts'],
        sender_id=sender_id,
        sender_name=sender_name,
        atlas_id=atlas_id,
        atlas_name=atlas_name,
        status='Spectrum CSV',
        note=csv_path,
        message_time=message_time,
    )


def process_message(message: dict,
                    client,
                    sender_cache: dict) -> None:
    """Fully processes a single slack message
    """
    # 0. Check if this is a csv message and save the file object (JSON dict with loads of fields)
    csv_file = find_csv_file(message)

    if csv_file is None and 'bot_id' in message and 'bot_profile' not in message:
        # Skip file uploads we don't care about storing (e.g. pictures)
        logging.info(f"Skipping bot message with no bot_profile and no csv file (likely a file upload), ts={message.get('ts')}")
        return

    # 1. Who sent us the message and what's their name?
    sender_id, sender_name = resolve_sender(message, client, sender_cache)

    # 2. Spectrum CSV file-share messages get their own path - they don't
    #    look like the usual bot status update / human chat messages
    if csv_file is not None:
        process_csv_message(message, csv_file, sender_id, sender_name, client)
        return

    # 3. Get the "parsed" dictionary with fields of interest
    if 'bot_id' in message:
        parsed = parse_bot_message(message)
        # If it's a bot message we use a specific parser because the json looks different
        # case in point: there is no top level 'text' field to read like in the human
        # messages (see else statement)
    else:
        # if no bot id it's a human, and we go and check or the REPORT 
        # keyword and extract relevant fields. 
        parsed = parse_human_message(message.get('text', ''))

    # 4 - Update the slack_messages table
    db.log_slack_message(
        slack_ts=message['ts'],
        sender_id=sender_id,
        sender_name=sender_name,
        telescope=parsed['telescope'],
        related_list=parsed['related_list'],
        atlas_id=parsed['atlas_id'],
        atlas_name=parsed['atlas_name'],
        ra=parsed['ra'],
        dec=parsed['dec'],
        latest_mag=parsed['latest_mag'],
        status=parsed['status'],
        note=parsed['note'],
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
