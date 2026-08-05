import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

### PARSER UTILITIES ###
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
