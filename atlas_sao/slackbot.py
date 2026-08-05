import logging

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


def resolve_telescope_and_list(sender_id: str, 
                               parsed_fields: dict, 
                               sender_lookup: dict) -> tuple:
    """Figure out which telescope and ATLAS object list is concerned by a given message"""
    telescope = parsed_fields.get('telescope')
    related_list = parsed_fields.get('related_list')

    if telescope is None or related_list is None:
        fallback = sender_lookup.get(sender_id, {})
        telescope = telescope or fallback.get('telescope')
        related_list = related_list or fallback.get('related_list')

    return telescope, related_list

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
    # I can forsee he will add the ATLAS_ID to the "section" block
    # which currently contains the ATLAS name. We may have to revisit this. 
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


def parse_bot_message(message: dict) -> dict:
    """Parses a single message from a bot"""
    fields = parse_blocks_fields(message.get('blocks', []))

    parsed = {
        # NOTE: I don't think we have telescope of related_list directly in the messages yet!
        # This will break? NO IT WON'T! .get() in a dict returns None instead of KeyError 
        # if key doesn't exist :) 
        'telescope': fields.get('telescope'),
        'related_list': fields.get('related_list'),
        'atlas_id': None,
        'ra': None,
        'dec': None,
        'latest_mag': None,
    }

    # NOTE: id Doesn't exist yet
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
