# HFS 2025 - original script
# Claude refactored for Goal 3 - modular refactor to match saltListWizard pattern (2026-06-29)
# HFS review and docstrings skipped for now as it's the same as the saltListWizard. can do later


import numpy as np
import pandas as pd
import atlasapiclient.client as ac
import logging
import atlas_sao.db as db

MAG_THRESHOLD = 17.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

##########################################
### MAIN LOGIC TO ADD TO THE LIST HERE ###
##########################################
def should_add_to_mookodi_live(entry, mag_threshold=MAG_THRESHOLD):
    if entry['object']['detection_list_id'] in (0, 11):  # 0=garbage, 11=pm_stars (HPM)
        return False

    classification = entry['object'].get('observation_status')
    if classification == '':
        classification = None
    if classification is not None:
        return False

    lc = entry.get('lc', [])
    if not lc:
        return False

    last_mag = lc[-1].get('mag')
    if last_mag is None:
        return False

    return last_mag < mag_threshold


def has_gone_stale(entry, n=10):
    """Looks at last N visits and returns TRUE if all non detections

    Parameters
    ----------
    entry: json
       The data for our atlas id of interest
    n: int, optional
       Number of consecutive data points to look at, Default is 10
    """
    lc = entry.get('lc', [])
    lcnondets = entry.get('lcnondets', [])

    # 1. LIST VISITS MJD AND WHETHER THEY ARE DETS OR NON DETS
    # lc is a list of dict. Each point is it's own dict with key
    # mjd and is_detection
    visits = (
        [{'mjd': point['mjd'], 'is_detection': True} for point in lc]
        + [{'mjd': point['mjd'], 'is_detection': False} for point in lcnondets]
    )

    # 2. CHECK IF WE EVEN HAVE ENOUGH DATA POINTS
    if len(visits) < n:
        return False

    # 3. SELECT THE LAST N POINTS
    recent_visits = sorted(visits, key=lambda visit: visit['mjd'])[-n:]

    # Return true IF AND ONLY IF all recent visits are NOT detections
    return all(not visit['is_detection'] for visit in recent_visits)


def add_targets_to_list(array_ids, list_name: str):
    if len(array_ids) == 0:
        return
    logging.info(f"Adding {len(array_ids)} targets to '{list_name}'...")
    ac.WriteToCustomList(array_ids=np.array(array_ids), list_name=list_name, get_response=True)


def remove_targets_from_list(array_ids, list_name: str, chunk_size: int = 25):
    if len(array_ids) == 0:
        return
    logging.info(f"Removing {len(array_ids)} targets from '{list_name}'...")
    # Claude wrote this fix (2026-07-20): RemoveFromCustomList.__init__ now always
    # fires the removal itself (atlasapiclient commit 7909a63) - calling
    # get_response() again here re-sent a delete for the last ID, which had
    # already been removed, causing a 400 that crashed the script.
    ac.RemoveFromCustomList(array_ids=np.array(array_ids), list_name=list_name, chunk_size=chunk_size)


def clean_up(objectgroupid: int,
             list_name: str):
    try:
        logging.info(f"Fetching {list_name} list (objectgroupid={objectgroupid})...")
        custom_list = ac.RequestCustomListsTable({'objectgroupid': objectgroupid}, get_response=True)

        if not custom_list.response_data:
            logging.info(f"{list_name} is empty - nothing to clean.")
            return []

        list_df = pd.DataFrame(custom_list.response_data).drop('object_group_id', axis=1)
        atlas_ids = list_df.transient_object_id.values.astype(str)
        logging.info(f"Fetched {len(atlas_ids)} entries from {list_name}.")

        try:
            logging.info(f"Requesting source data for {list_name} members...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=np.array(atlas_ids),
                mjdthreshold=60_500,
                chunk_size=25
            )
            multi_data.chunk_get_response_quiet()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception(f"Error fetching source data for {list_name} members.")
            raise

        to_remove = []
        for entry in multi_data.response_data:
            try:
                atlas_id = entry['object']['id']
                detection_list_id = entry['object']['detection_list_id']
                classification = entry['object'].get('observation_status')

                if classification == '':
                    classification = None

                if classification is not None or detection_list_id in (0, 5, 11):  
                    # 0=garbage, 5=attic, 11=pm_stars (HPM)
                    to_remove.append(atlas_id)
                elif has_gone_stale(entry):
                    to_remove.append(atlas_id)

            except Exception:
                logging.exception(f"Error processing {list_name} member entry.")

        return to_remove

    except Exception:
        logging.exception(f"Failed to fetch {list_name}.")
        raise


def fill_up(mag_threshold=MAG_THRESHOLD, 
            db_path=None):
    """
    Fills up the Bright 100 Mpc Transient list

    Note
    ----
    This version of the fill_up function checks wether an alert has already been removed
    from this list in the path (checks list_removed_at not NULL in slack_messages).

    This will prevent an object from RE-ENTERNG THE QUEUE unless I alter the db.

    If These manual re-observation because routine I will need to find a more nuanced
    logic so I don't have to alter the column in the db.

    Parameters
    -----------
    mag_threshold: float
       The Mangtidue threshold for what is "Bright" default is 17

    db_path: str
       Path to the log.db 
    """

    try:
        # 1. Check what's already in the list
        logging.info("Fetching current mookodi_live list to check existing members...")
        ## Note: This is called "live" because historically the list was called Mookodi Live
        live = ac.RequestCustomListsTable({'objectgroupid': 16}, get_response=True)
        if live.response_data:
            live_df = pd.DataFrame(live.response_data).drop('object_group_id', axis=1)
            live_ids_set = set(live_df.transient_object_id.values.astype(str))
        else:
            live_ids_set = set()
        logging.info(f"{len(live_ids_set)} objects currently in mookodi_live.")

        # 2. Check what objects have already been observed
        logging.info("Fetching IDs previously Observed & removed from Bright 100Mpc list...")
        ## This just looks for any row in slack_messages where related_list = this one and list_removed_at is NOT NULL
        removed_ids_set = set(str(id_) for id_ in db.get_removed_atlas_ids_for_list(
            'Bright 100Mpc Southern Transients', db_path=db_path))
        logging.info(f"{len(removed_ids_set)} objects previously observed & removed - excluded from re-add.")

        # 3. Check our input to see if there are candidates to be added to the list
        #    That is the Southern 100Mpc Transients but historically was refered to as the Staging list
        logging.info("Fetching Mookodi staging list (objectgroupid=2)...")
        staging = ac.RequestCustomListsTable({'objectgroupid': 2}, get_response=True)

        if not staging.response_data:
            logging.info("Mookodi staging list is empty - nothing to evaluate.")
            return [], {}

        staging_df = pd.DataFrame(staging.response_data).drop('object_group_id', axis=1)
        staging_ids_set = set(staging_df.transient_object_id.values.astype(str))
        logging.info(f"Fetched {len(staging_ids_set)} entries from staging list.")

        # Finding set of valid candidate ids by removing already live IDs and those already removed
        candidate_ids =  staging_ids_set - removed_ids_set - live_ids_set
        logging.info(f"{len(candidate_ids)} staging objects not already in mookodi_live or previously removed.")

        if len(candidate_ids) == 0:
            logging.info("No new candidates to evaluate.")
            return [], {}

        try:
            logging.info("Requesting source data for staging candidates...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=np.array(list(candidate_ids)),
                mjdthreshold=61_000, # TODO: make dynamic!!
                chunk_size=25
            )
            multi_data.chunk_get_response_quiet()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for staging candidates.")
            raise

        to_add = []
        vra_scores = {}
        for entry in multi_data.response_data:
            try:
                if should_add_to_mookodi_live(entry, mag_threshold):
                    atlas_id = entry['object']['id']
                    to_add.append(atlas_id)
                    vra_scores[str(atlas_id)] = entry['object'].get('vra')
            except Exception:
                logging.exception("Error processing staging candidate entry.")

        return to_add, vra_scores

    except Exception:
        logging.exception("Failed to process staging list for mookodi_live candidates.")
        raise


if __name__ == "__main__":
    to_remove_live = clean_up(objectgroupid=16, list_name='bright_south_transients_100mpc')
    remove_targets_from_list(to_remove_live, list_name='bright_south_transients_100mpc')
    db.log_removed(to_remove_live, 'bk_young_fast_track')

    to_remove_base = clean_up(objectgroupid=2, list_name='south_transients_100mpc')
    remove_targets_from_list(to_remove_base, list_name='south_transients_100mpc')

    to_add, vra_scores = fill_up()
    add_targets_to_list(to_add, list_name='bright_south_transients_100mpc')
    db.log_added(to_add, 'bk_young_fast_track', vra_scores=vra_scores)
