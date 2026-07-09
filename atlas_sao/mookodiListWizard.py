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
    if entry['object']['detection_list_id'] == 0:
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
    # Claude wrote this for issue #42 (2026-06-17): RemoveFromCustomList only
    # auto-fires when it had to chunk; call explicitly for small batches.
    if len(array_ids) <= chunk_size:
        remover.get_response()


def clean_up(objectgroupid: int, list_name: str):
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

                if classification is not None or detection_list_id in (0, 5):
                    to_remove.append(atlas_id)

            except Exception:
                logging.exception(f"Error processing {list_name} member entry.")

        return to_remove

    except Exception:
        logging.exception(f"Failed to fetch {list_name}.")
        raise


def fill_up(mag_threshold=MAG_THRESHOLD):
    try:
        logging.info("Fetching current mookodi_live list to check existing members...")
        live = ac.RequestCustomListsTable({'objectgroupid': 16}, get_response=True)
        if live.response_data:
            live_df = pd.DataFrame(live.response_data).drop('object_group_id', axis=1)
            live_ids_set = set(live_df.transient_object_id.values.astype(str))
        else:
            live_ids_set = set()
        logging.info(f"{len(live_ids_set)} objects currently in mookodi_live.")

        logging.info("Fetching Mookodi staging list (objectgroupid=2)...")
        staging = ac.RequestCustomListsTable({'objectgroupid': 2}, get_response=True)

        if not staging.response_data:
            logging.info("Mookodi staging list is empty - nothing to evaluate.")
            return [], {}

        staging_df = pd.DataFrame(staging.response_data).drop('object_group_id', axis=1)
        staging_ids = staging_df.transient_object_id.values.astype(str)
        logging.info(f"Fetched {len(staging_ids)} entries from staging list.")

        candidate_ids = np.array([id_ for id_ in staging_ids if id_ not in live_ids_set])
        logging.info(f"{len(candidate_ids)} staging objects not already in mookodi_live.")

        if len(candidate_ids) == 0:
            logging.info("No new candidates to evaluate.")
            return [], {}

        try:
            logging.info("Requesting source data for staging candidates...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=candidate_ids,
                mjdthreshold=60_500,
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
    to_remove_live = clean_up(objectgroupid=16, list_name='mookodi_live')
    remove_targets_from_list(to_remove_live, list_name='mookodi_live')
    db.log_removed(to_remove_live, 'bk_young_fast_track')

    to_remove_base = clean_up(objectgroupid=2, list_name='mookodi')
    remove_targets_from_list(to_remove_base, list_name='mookodi')

    to_add, vra_scores = fill_up()
    add_targets_to_list(to_add, list_name='mookodi_live')
    db.log_added(to_add, 'bk_young_fast_track', vra_scores=vra_scores)
