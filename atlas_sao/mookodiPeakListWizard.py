# Claude wrote this for Goal 3 - Mookodi Peak list wizard (2026-06-29)
# HFS review, added comments and docstrings 2026-06-29

from datetime import datetime
import numpy as np
import pandas as pd
import atlasapiclient.client as ac
import logging
import atlas_sao.db as db

### CONSTANTS
# this threshold used as proxy for "at peak" for now, see README
MAG_THRESHOLD = 16.9
# require this many of the most recent lc points to independently pass the
# brightness cut, so a single bogus bright detection can't get an object onto the list
N_RECENT_POINTS = 3
# how many days of lightcurve history to request — is_at_peak needs the last N_RECENT_POINTS
LOOKBACK_DAYS = 60
MJD_EPOCH = datetime(1858, 11, 17)


def _mjd_threshold():
    """HACK - Not suitable for most MJD calculations because only precise to the day 
    but avoids adding an astropy dependency to this basic cut we are trying to make
    """
    return (datetime.utcnow() - MJD_EPOCH).days - LOOKBACK_DAYS

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

    Non-detections don't show up in `lc` - they live in `lcnondets` (limiting
    mag only, no mag/magerr). So the last N_RECENT_POINTS "visits" are found
    by merging `lc` and `lcnondets` on mjd; any of those most-recent visits
    landing in `lcnondets` means the object hasn't actually been seen lately,
    even if `lc` on its own still ends on old bright points.

    The last N_RECENT_POINTS visits must each be real detections in `lc`
    that are brighter than MAG_THRESHOLD even allowing for their 1-sigma
    error bar (mag - magerr < MAG_THRESHOLD). Non-detections or fewer than
    N_RECENT_POINTS visits total fail this check.

    Return
    ------
    bool
    """
    if entry['object']['detection_list_id'] == 0:
        return False

    lc = entry.get('lc', [])
    lcnondets = entry.get('lcnondets', [])

    visits = (
        [{'mjd': point['mjd'], 'is_detection': True, 'mag': point.get('mag'), 'magerr': point.get('magerr')}
         for point in lc]
        + [{'mjd': point['mjd'], 'is_detection': False} for point in lcnondets]
    )
    if len(visits) < N_RECENT_POINTS:
        return False

    recent_visits = sorted(visits, key=lambda visit: visit['mjd'])[-N_RECENT_POINTS:]

    for visit in recent_visits:
        if not visit['is_detection']:
            return False
        mag = visit.get('mag')
        magerr = visit.get('magerr')
        if mag is None or magerr is None or mag <= 0:
            return False
        if not (mag - magerr < MAG_THRESHOLD):
            return False

    return True


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
    # Claude wrote this fix (2026-07-20): RemoveFromCustomList.__init__ now always
    # fires the removal itself (atlasapiclient commit 7909a63) - calling
    # get_response() again here re-sent a delete for the last ID, which had
    # already been removed, causing a 400 that crashed the script.
    ac.RemoveFromCustomList(array_ids=np.array(array_ids), list_name=list_name, chunk_size=chunk_size)


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
                mjdthreshold=_mjd_threshold(),
                chunk_size=50
            )
            multi_data.chunk_get_response()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for Mookodi Peak members.")
            raise

        to_remove = []
        for entry in multi_data.response_data:
            try:
                atlas_id = str(entry['object']['id'])
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

        logging.info("Fetching active candidates from xtgal_3mnths...")
        follow_up_ids = np.array([str(id_) for id_ in db.get_active_xtgal_ids()])
        logging.info(f"Fetched {len(follow_up_ids)} active entries from xtgal_3mnths.")

        if len(follow_up_ids) == 0:
            logging.info("xtgal_3mnths is empty - nothing to evaluate.")
            return [], {}

        candidate_ids = np.array([id_ for id_ in follow_up_ids if id_ not in peak_ids_set])
        logging.info(f"{len(candidate_ids)} follow-up objects not already in Mookodi Peak list.")

        if len(candidate_ids) == 0:
            logging.info("No new candidates to evaluate.")
            return [], {}

        try:
            logging.info("Requesting source data for staging candidates...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=candidate_ids,
                mjdthreshold=_mjd_threshold(),
                chunk_size=50
            )
            multi_data.chunk_get_response()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for follow-up candidates.")
            raise

        to_add = []
        vra_scores = {}
        for entry in multi_data.response_data:
            try:
                #  CALLING SPECIAL FUNCTION WHERE ADDING LOGIC LIVES
                # ################################################## #
                if is_at_peak(entry):
                    atlas_id = str(entry['object']['id'])
                    to_add.append(atlas_id)
                    vra_scores[atlas_id] = entry['object'].get('vra')
            except Exception:
                logging.exception("Error processing follow-up candidate entry.")

        return to_add, vra_scores

    except Exception:
        logging.exception("Failed to process follow-up list for Mookodi Peak candidates.")
        raise


if __name__ == "__main__":
    to_remove = clean_up()
    remove_targets_from_list(to_remove, list_name='mookodi_peak')
    db.log_removed(to_remove, 'bk_peak')

    to_add, vra_scores = fill_up()
    logging.info(f"to_add IDs and types: {[(id_, type(id_)) for id_ in to_add]}")
    add_targets_to_list(to_add, list_name='mookodi_peak')
    db.log_added(to_add, 'bk_peak', vra_scores=vra_scores)
