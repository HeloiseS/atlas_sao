# Claude wrote this for Goal 2 - SALT list wizard (2026-06-26)
# HFS Major refactor, comments and docstrings (2026-06-26)

import numpy as np
import pandas as pd
import atlasapiclient.client as ac
import logging
import atlas_sao.db as db

### CONSTANTS
# NOTE: eventually these may come from CL arguments or config file
SALT_VRA_THRESHOLD = 9.0
SALT_SHERLOCK_EXCLUDE = 'ORPHAN'
SALT_DEC_MAX = 10.0

### LOGGING SET UP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)


def should_add_to_salt(entry, vra_threshold=SALT_VRA_THRESHOLD, sherlock_exclude=SALT_SHERLOCK_EXCLUDE):
    """Decides if an alert meets requirements to be added to SALT list

    You can change the logic here without having to re-write the `fill_up` function. 

    Returns
    --------
    True or False
    """
    if entry['object']['detection_list_id'] == 0:
        return False
    if entry['object']['dec'] >= SALT_DEC_MAX:
        # For SALT we don't want anything with declination +10 or above.
        return False
    vra = entry['object'].get('vra')
    if vra is None or vra <= vra_threshold:
        return False
    if entry['object'].get('sherlockClassification') == sherlock_exclude:
        return False
    return True


def add_targets_to_list(array_ids, list_name: str):
    if len(array_ids) == 0:
        return
    logging.info(f"Adding {len(array_ids)} targets to '{list_name}'...")
    ac.WriteToCustomList(array_ids=np.array(array_ids), list_name=list_name, get_response=True)


def remove_targets_from_list(array_ids, list_name: str, chunk_size: int = 25):
    if len(array_ids) == 0:
        return
    logging.info(f"Removing {len(array_ids)} targets from '{list_name}'...")
    ac.RemoveFromCustomList(array_ids=np.array(array_ids), list_name=list_name, chunk_size=chunk_size)


def clean_up():
    """Finds ATLAS IDs to be cleaned up from SALT list (classified or garbage)

    Returns
    --------
    list of ATLAS IDs to be removed from SALT list
    """

    try:
        logging.info("Fetching SALT list (objectgroupid=14)...")
        salt = ac.RequestCustomListsTable({'objectgroupid': 14}, get_response=True)

        if not salt.response_data:
            logging.info("SALT list is empty - nothing to clean.")
            return []

        salt_df = pd.DataFrame(salt.response_data).drop('object_group_id', axis=1)
        salt_ids = salt_df.transient_object_id.values.astype(str)
        logging.info(f"Fetched {len(salt_ids)} entries from SALT list.")

        try:
            logging.info("Requesting source data for SALT members...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=np.array(salt_ids),
                mjdthreshold=60_500,
                chunk_size=25
            )
            multi_data.chunk_get_response_quiet()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for SALT members.")
            raise

        to_remove = []
        for entry in multi_data.response_data:
            try:
                atlas_id = entry['object']['id']
                detection_list_id = entry['object']['detection_list_id']
                classification = entry['object'].get('observation_status')

                if classification == '':
                    classification = None

                if classification is not None or detection_list_id in (0, 5):
                    to_remove.append(atlas_id)

            except Exception:
                logging.exception("Error processing SALT member entry.")

        return to_remove

    except Exception:
        logging.exception("Failed to fetch SALT list.")
        raise


def fill_up(vra_threshold=SALT_VRA_THRESHOLD, sherlock_exclude=SALT_SHERLOCK_EXCLUDE):
    """Finds ATLAS IDs to be added to the SALT List. 

    Note
    -----
    The constrains and logic to decide which alerts get put in the list 
    LIVE IN ANOTHER FUNCTION: `should_add_to_salt`

    Returns
    -------
    List of ATLAS IDs
    """

    try:
        logging.info("Fetching current SALT list to check existing members...")
        salt = ac.RequestCustomListsTable({'objectgroupid': 14}, get_response=True)
        if salt.response_data:
            salt_df = pd.DataFrame(salt.response_data).drop('object_group_id', axis=1)
            salt_ids_set = set(salt_df.transient_object_id.values.astype(str))
        else:
            salt_ids_set = set()
        logging.info(f"{len(salt_ids_set)} objects currently in SALT list.")

        logging.info("Fetching eyeball list (pre-filtered by VRA/Dec at the API level)...")
        eyeball = ac.RequestATLASIDsFromWebServerList(
            list_name='eyeball',
            vra_gte=vra_threshold,
            dec_lte=SALT_DEC_MAX,
        )
        eyeball_ids = np.array(eyeball.atlas_id_list_str)
        logging.info(f"Fetched {len(eyeball_ids)} entries from eyeball list.")

        candidate_ids = np.array([id_ for id_ in eyeball_ids if id_ not in salt_ids_set])
        logging.info(f"{len(candidate_ids)} eyeball objects not already in SALT list.")

        if len(candidate_ids) == 0:
            logging.info("No new candidates to evaluate.")
            return [], {}

        try:
            logging.info("Requesting source data for eyeball candidates...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=candidate_ids,
                mjdthreshold=60_500,
                chunk_size=25
            )
            multi_data.chunk_get_response_quiet()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for eyeball candidates.")
            raise

        to_add = []
        vra_scores = {}
        for entry in multi_data.response_data:
            try:
                #  CALLING SPECIAL FUNCTION WHERE ADDING LOGIC LIVES
                # ################################################## #
                if should_add_to_salt(entry, vra_threshold, sherlock_exclude):
                    atlas_id = entry['object']['id']
                    to_add.append(atlas_id)
                    vra_scores[str(atlas_id)] = entry['object'].get('vra')
            except Exception:
                logging.exception("Error processing eyeball candidate entry.")

        return to_add, vra_scores

    except Exception:
        logging.exception("Failed to process eyeball list for SALT candidates.")
        raise


if __name__ == "__main__":
    to_remove = clean_up()
    remove_targets_from_list(to_remove, list_name='salt')
    db.log_removed(to_remove, 'bk_young_not_fast_track')

    to_add, vra_scores = fill_up()
    add_targets_to_list(to_add, list_name='salt')
    db.log_added(to_add, 'bk_young_not_fast_track', vra_scores=vra_scores)
