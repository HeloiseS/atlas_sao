# Claude wrote this for Goal 3 - Mookodi Peak list wizard (2026-06-29)
# HFS review, added comments and docstrings 2026-06-29

import numpy as np
import pandas as pd
import atlasapiclient.client as ac
import logging

### CONSTANTS
# this threshold used as proxy for "at peak" for now, see README
MAG_THRESHOLD = 16.0

### LOGGING SET UP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

##########################################
### MAIN LOGIC TO ADD TO THE LIST HERE ###
##########################################
def is_at_peak(entry):
    """ Function that contains the logic that decides if a lightcurve is at peak
    Here there is no constraint that the object must be unclassified. 

    Return
    ------
    bool
    """
    if entry['object']['detection_list_id'] == 0:
        return False

    lc = entry.get('lc', [])
    if not lc:
        return False

    last_mag = lc[-1].get('mag')
    if last_mag is None:
        return False

    return last_mag < MAG_THRESHOLD


# ################################ #
#          Utility Functions       #
# ################################ #

def add_targets_to_list(array_ids, list_name: str):
    """Add array of ATLAS IDs to a specific list

    Parameters
    -----------
    array_ids: np.array
        Array of valid ATLAS_IDs
    list_name: str
        A valid list name in atlaspiclient. Valid names are keys in the dictionary
        `atlasapiclient.utils.dict_list_id`
    """

    if len(array_ids) == 0:
        return
    logging.info(f"Adding {len(array_ids)} targets to '{list_name}'...")
    ac.WriteToCustomList(array_ids=np.array(array_ids), list_name=list_name, get_response=True)


def remove_targets_from_list(array_ids, list_name: str, chunk_size: int = 25):
    """Remove array of ATLAS IDs to a specific list                                                      
                                                                                                      
    Parameters                                                                                        
    -----------                                                                                       
    array_ids: np.array                                                                               
        Array of valid ATLAS_IDs                                                                      
    list_name: str                                                                                    
        A valid list name in atlaspiclient. Valid names are keys in the dictionary                    
        `atlasapiclient.utils.dict_list_id`                                                           
    chunk_size: int
        Default is 25. That's because we used to get error 500s from the server when 
        not suing small chunks. This may not be an issue anymore but I've kept this in. 
    """       
    if len(array_ids) == 0:
        return
    logging.info(f"Removing {len(array_ids)} targets from '{list_name}'...")
    remover = ac.RemoveFromCustomList(array_ids=np.array(array_ids), list_name=list_name, chunk_size=chunk_size)
    # Claude wrote this for issue #42 (2026-06-17): RemoveFromCustomList only
    # auto-fires when it had to chunk; call explicitly for small batches.
    if len(array_ids) <= chunk_size:
        remover.get_response()


def clean_up():
    """Finds targets that are now too faint and need to be cleaned up

    Returns
    -------
    list

    """
    try:
        logging.info("Fetching Mookodi Peak list (objectgroupid=17)...")
        peak = ac.RequestCustomListsTable({'objectgroupid': 17}, get_response=True)

        if not peak.response_data:
            logging.info("Mookodi Peak list is empty - nothing to clean.")
            return []

        peak_df = pd.DataFrame(peak.response_data).drop('object_group_id', axis=1)
        peak_ids = peak_df.transient_object_id.values.astype(str)
        logging.info(f"Fetched {len(peak_ids)} entries from Mookodi Peak list.")

        try:
            logging.info("Requesting source data for Mookodi Peak members...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=np.array(peak_ids),
                mjdthreshold=60_500,
                chunk_size=25
            )
            multi_data.chunk_get_response_quiet()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for Mookodi Peak members.")
            raise

        to_remove = []
        for entry in multi_data.response_data:
            try:
                atlas_id = entry['object']['id']
                too_faint = not is_at_peak(entry)

                if too_faint:
                    to_remove.append(atlas_id)

            except Exception:
                logging.exception("Error processing Mookodi Peak member entry.")

        return to_remove

    except Exception:
        logging.exception("Failed to fetch Mookodi Peak list.")
        raise


def fill_up():
    """Finds the ATLAS Transients to add to the Mookodi at peak list 

    Returns
    --------
    list
    """
    try:
        logging.info("Fetching current Mookodi Peak list to check existing members...")
        peak = ac.RequestCustomListsTable({'objectgroupid': 17}, get_response=True)
        if peak.response_data:
            peak_df = pd.DataFrame(peak.response_data).drop('object_group_id', axis=1)
            peak_ids_set = set(peak_df.transient_object_id.values.astype(str))
        else:
            peak_ids_set = set()
        logging.info(f"{len(peak_ids_set)} objects currently in Mookodi Peak list.")

        # TODO: follow-up list is a temporary proxy for the Good list (detection_list_id=1).
        # Good list is unbounded and the API has no date filtering on list membership,
        # making it unscalable. Revisit when the API supports date-filtered list queries.
        logging.info("Fetching follow-up list...")
        follow_up = ac.RequestATLASIDsFromWebServerList(list_name='follow_up')
        follow_up_ids = np.array(follow_up.atlas_id_list_str)
        logging.info(f"Fetched {len(follow_up_ids)} entries from follow-up list.")

        if len(follow_up_ids) == 0:
            logging.info("Follow-up list is empty - nothing to evaluate.")
            return []

        candidate_ids = np.array([id_ for id_ in follow_up_ids if id_ not in peak_ids_set])
        logging.info(f"{len(candidate_ids)} follow-up objects not already in Mookodi Peak list.")

        if len(candidate_ids) == 0:
            logging.info("No new candidates to evaluate.")
            return []

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
            logging.exception("Error fetching source data for follow-up candidates.")
            raise

        to_add = []
        for entry in multi_data.response_data:
            try:
                #  CALLING SPECIAL FUNCTION WHERE ADDING LOGIC LIVES
                # ################################################## #
                if is_at_peak(entry):
                    to_add.append(entry['object']['id'])
            except Exception:
                logging.exception("Error processing follow-up candidate entry.")

        return to_add

    except Exception:
        logging.exception("Failed to process follow-up list for Mookodi Peak candidates.")
        raise


if __name__ == "__main__":
    to_remove = clean_up()
    remove_targets_from_list(to_remove, list_name='mookodi_peak')
    to_add = fill_up()
    add_targets_to_list(to_add, list_name='mookodi_peak')
