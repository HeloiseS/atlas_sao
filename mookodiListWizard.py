"""
Description
------------
A Script to:
    1) Create and clean the live Mookodi list - feed to the SAOO
    2) Clean the Base Mookodi list, which contains all nearby  (<100Mpc)
    transients with VRA scores > [Mookodi_threshold]


Dev Notes
----------

Clean Up logic
~~~~~~~~~~~~~~~
- If an alert has already been classified in TNS
- If an alert is in the garbage list (0)

Then remove from the Mookodi Base (Custom List 2) and Mookodi Live (Custom list 16)

Wizardry in Chunking
~~~~~~~~~~~~~~~~~~~~~
The ATLAS API Client, when requesting batches of data, sometimes suffers from
50* errors. Despite the fact that the limit is 100 alert requests at a time,
this very often fails. I have found that smaller chunks of 25 work, at least
for the READ operations.

Right now it looks like with smaller chunks (25) it works when Requesting data
However it fails fails fails when trying to remove alerts from a list or add to a list.

For WRITE operations chunking just doens't seem to work at all, and the work around
is to do one request at a time, which is a pain and so I made a wrapper.
I don't love it, it's a wrapper of a wrapper, but it just needs to run.
They also encapsulate some logging so we can keep track of what's going on.
"""

import pandas as pd
import numpy as np
import atlasapiclient.client as ac
import logging


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        #logging.FileHandler("atlas_debug.log"),
        logging.StreamHandler()
    ]
)

# Claude wrote this (2026-06-17): batched add/remove now that atlasapiclient
# issues #42/#43 are fixed upstream - one call per list instead of one per ID.
def add_targets_to_list(array_ids, list_name: str):
    if len(array_ids) == 0:
        return
    logging.info(f"Adding {len(array_ids)} targets to '{list_name}'...")
    ac.WriteToCustomList(array_ids=np.array(array_ids), list_name=list_name, get_response=True)


def remove_targets_from_list(array_ids, list_name: str, chunk_size: int = 25):
    if len(array_ids) == 0:
        return
    logging.info(f"Removing {len(array_ids)} targets from '{list_name}'...")
    remover = ac.RemoveFromCustomList(array_ids=np.array(array_ids), list_name=list_name, chunk_size=chunk_size)
    # RemoveFromCustomList only auto-fires the request in __init__ when it had
    # to chunk (batch > chunk_size); below that, get_response() must be called
    # explicitly - its get_response constructor kwarg is otherwise unused.
    if len(array_ids) <= chunk_size:
        remover.get_response()


if __name__ == "__main__":
    ###########################################################################
    # Cleaning Up the Mookodi Live List
    try:
        logging.info("Fetching custom list (objectgroupid=16)...")
        mokoodi = ac.RequestCustomListsTable({'objectgroupid': 16}, get_response=True)    # Get the list of alerts in list

        if len(mokoodi.response_data) != 0:                                               # If list not empty
            logging.info("Mookodi Live is not empty - checking if needs cleaning")
            mokoodi_list_df = pd.DataFrame(mokoodi.response_data).drop('object_group_id',
                                                                       axis=1)            # Turn response into dataframe

            atlas_ids = mokoodi_list_df.transient_object_id.values.astype(str)            # Get list of ATLAS_IDs...
            logging.info(f"Fetched {len(atlas_ids)} entries from custom list.")

            try:                                                                          # and get their full data from server
                logging.info("Requesting source data in chunks...")
                multi_data = ac.RequestMultipleSourceData(
                    array_ids=np.array(atlas_ids),
                    mjdthreshold=60_500,
                    chunk_size=25  # or 50, or whatever works
                )
                multi_data.chunk_get_response_quiet()
                logging.info(f"Received data for {len(multi_data.response_data)} sources.")

            except Exception as e:                                                        # wrapped in exception in case err 50*
                logging.exception("Error fetching multiple source data.")
                raise

            to_remove = []                                                                # Now set up list to store ATLAS_IDs to remove

            for entry in multi_data.response_data:                                        # Grab data for each alert and
                try:
                    atlas_id = entry['object']['id']                                      # get ATLAS_ID
                    detection_list_id = entry['object']['detection_list_id']              # get list number  (0 for garbage)
                    classification = entry['object'].get('observation_status')            # get observation status (on TNS)

                    logging.debug(f"ATLAS ID {atlas_id} -> classification: {classification}" )

                    if classification is not None or detection_list_id == 0:              # If classified or garbage...
                        to_remove.append(atlas_id)                                        # add to the "to_remove" list

                except Exception as e:
                    logging.exception(f"Error processing source data entry.")

            remove_targets_from_list(to_remove, list_name='mookodi_live')                 # Remove alerts flagged above


    except Exception as e:                                                                # This catches errors from RequestCustomList
        logging.exception("Failed to fetch Live Mokoodi list.")
        raise

    # #########################################################
    # Now looking at the Base Mookodi List. Similar process.
    try:
        logging.info("Fetching Mokoodi Base List (objectgroupid=2)...")
        mokoodi = ac.RequestCustomListsTable({'objectgroupid': 2}, get_response=True)     # Get the list of alerts in list

        if len(mokoodi.response_data) != 0:                                               # If list not empty
            logging.info("Mookodi Base is not empty - go ahead")
            mokoodi_list_df = pd.DataFrame(mokoodi.response_data).drop('object_group_id',
                                                                       axis=1)            # Turn response into dataframe

            atlas_ids = mokoodi_list_df.transient_object_id.values.astype(str)            # Get list of ATLAS_IDs...
            logging.info(f"Fetched {len(atlas_ids)} entries from custom list.")

            try:                                                                          # and get their full data from server
                logging.info("Requesting source data in chunks...")
                multi_data = ac.RequestMultipleSourceData(
                    array_ids=np.array(atlas_ids),
                    mjdthreshold=60_500,
                    chunk_size=25  # or 50, or whatever works
                )
                multi_data.chunk_get_response_quiet()
                logging.info(f"Received data for {len(multi_data.response_data)} sources.")

            except Exception as e:                                                        # wrapped in exception in case err 50*
                logging.exception("Error fetching multiple source data.")
                raise

            good_targets = []                                                             # Now set up list to store ATLAS_IDs to ADD to Live list
            to_remove = []                                                                # Now set up list to store ATLAS_IDs to remove from Base

            for entry in multi_data.response_data:                                        # Grab data for each alert and
                try:
                    atlas_id = entry['object']['id']                                      # get ATLAS_ID
                    detection_list_id = entry['object']['detection_list_id']              # get detection_list number (0=garbage)
                    classification = entry['object'].get('observation_status')            # get classification status (TNS)
                    lc = entry.get('lc', [])                                              # get lightcurve data

                    if not lc:                                                            # if no lightcurve, log and go to next object
                        logging.debug(f"No lightcurve for {atlas_id}. Skip.")
                        continue

                    last_mag = lc[-1].get('mag')
                    if last_mag is None:                                                  # Can't remember if need this
                        logging.debug(f"No mag in last LC point for {atlas_id}. Skip.")
                        continue

                    logging.debug(f"ATLAS ID {atlas_id}: "\
                                   "classification: {classification}, "\
                                   "last_mag: {last_mag}")

                    if classification == '':                                              # For some reason I've found instances
                        logging.debug(f"classification was empty str - changed to None")  # of empty str instead of None, which
                        classification = None                                             # breaks the logic below. (2025-10-01)

                    # If not classified, brighter than 17th mag and not garbage -> GOOD!
                    if classification is None and last_mag < 17.0 and detection_list_id != 0:
                        good_targets.append(atlas_id)
                    elif classification is not None or detection_list_id == 0:            # if classified or garbage -> to remove.
                        logging.debug(f"{type(classification)}{classification}")
                        logging.debug(f"ATLAS_ID {atlas_id} to remove. "\
                                       "Classification: {classification} | "\
                                       "list_id: {detection_list_id}")
                        to_remove.append(atlas_id)

                except Exception as e:
                    logging.exception(f"Error processing source data entry.")

            add_targets_to_list(good_targets, list_name='mookodi_live')                   # ADD GOOD TARGETS TO THE LIVE LIST
            remove_targets_from_list(to_remove, list_name='mookodi')                      # REMOVE BAD TARGETS FROM BASE LIST

    except Exception as e:                                                                # This catches errors from RequestCustomList
        logging.exception("Failed to fetch Base Mokoodi list.")
        raise
