# Claude wrote this for Goal 2 - SALT list wizard (2026-06-26)
# HFS Major refactor, comments and docstrings (2026-06-26)


from datetime import datetime
import numpy as np
import pandas as pd
import atlasapiclient.client as ac
import logging
import atlas_sao.db as db

### CONSTANTS
# NOTE: eventually these may come from CL arguments or config file
SALT_DEC_MAX = 10.0
SALT_FRESHNESS_DAYS = 7
SALT_NONDET_CLUSTER_MIN = 2
SALT_MAX_SPAN_DAYS = 7  # CLAUDE EDIT - PLEASE REVIEW: added 2026-08-27, drop objects whose detections span more than this
MJD_EPOCH = datetime(1858, 11, 17)

### LOGGING SET UP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)


def _current_mjd():
    # 864000.0 is number of seconds in a day. This gives the mjd with seconds level accuracy rather than day accuracy
    return (datetime.utcnow() - MJD_EPOCH).total_seconds() / 86400.0



def _cluster_nondetection_nights(lcnondets, window_days=1):
    """Cluster non detections into clumps of non-detection NIGHTS (within 24h)
    
    Parameters
    -----------
    lcnondets: dictionary
        Very specifically the lcnondets dictionary (not ANY dictionary)
    window_days: int
        Number of days used to clump our detections. Default = 1
    """
    mjds = sorted(point['mjd'] for point in lcnondets)

    if not mjds:
        return []

    # List of lists. First member of first list is the first data point
    clusters = [[mjds[0]]]

    for mjd in mjds[1:]:
        # If the mjd of the current point MINUS the latest MJD we 
        # recorded is less than the number of days we want our clumps to span
        #... Then we add this our current clump.
        if mjd - clusters[-1][-1] <= window_days:
            clusters[-1].append(mjd)
        else:
            # If we're outside that period of time we start a NEW clump 
            # (new list within our list of lists)
            clusters.append([mjd])
    return clusters


def has_recent_nondetection(entry,
                             N_days=SALT_FRESHNESS_DAYS,
                             N_nondet_min=SALT_NONDET_CLUSTER_MIN
                             ):
    """Check whether the last non-detections are recent (so young-ish object)
    
    Parameters
    ----------
    entry: dict
       Our ATLAS data, one entry (one object). Must contain an lcnondets dictionary
    N_days: int
       Number of days we're going to look back for our non detections (how recent is recent?)
    N_nondet_min: int
       Minimum number of non detections rewuired to consider that a night's nondetections are valid.
       Default is 2.
    """
    lcnondets = entry.get('lcnondets', [])

    # 1. Group our nondetections
    clusters = _cluster_nondetection_nights(lcnondets)
    # 2. Only keep the clumps that have at LEAST N nondetections
    qualifying = [c for c in clusters if len(c) >= N_nondet_min]
    if not qualifying:
        # if non qualify, good bye
        return False

    # 3. If some qualify, look at the latest
    most_recent_night_mjd = qualifying[-1][-1]
    # 4. Boolean: check if it's been more than N_days!
    return (_current_mjd() - most_recent_night_mjd) <= N_days


def is_not_too_old(entry, N_span_days=SALT_MAX_SPAN_DAYS):
    """Check if old! Checks that our lightcurve (the actual detections) don't span too many days"""
    lc = entry.get('lc', [])
    if not lc:
        return False
    mjds = [point['mjd'] for point in lc]
    return (max(mjds) - min(mjds)) <= N_span_days


def has_non_w_detection(entry):
    """Check if our detections are exclusively w band"""
    # NOTE: HFS 2026-08-27: I can see where that could fail. If we have a spurious
    # detection in c or o in the past and then a bunch of w band. 
    # NO ACTION for now. Check if SALT list gets too many contaminants before making this 
    # function more complex. 
    lc = entry.get('lc', [])
    return not all(point.get('filter') == 'w' for point in lc)


def should_add_to_salt(entry,
                        dec_max=SALT_DEC_MAX,
                        N_days=SALT_FRESHNESS_DAYS,
                        N_nondet_min=SALT_NONDET_CLUSTER_MIN,
                        N_span_days=SALT_MAX_SPAN_DAYS):
    """Decides if an alert meets requirements to be added to SALT list

    You can change the logic here without having to re-write the `fill_up` function.

    Parameters
    ----------
    entry: dict
       Our ATLAS data, one entry (one object). Must contain an lcnondets dictionary
    dec_max: float
       Max declination we consider for our ATLAS objects. Default is +10 degrees
    N_days: int
       Number of days we're going to look back for our non detections (how recent is recent?)
    N_nondet_min: int
       Minimum number of non detections rewuired to consider that a night's nondetections are valid.
       Default is 2.

    Returns
    --------
    True or False
    """
    classification = entry['object'].get('observation_status')

    if classification == '':
        classification = None
    if classification is not None:
        return False
    
    if entry['object']['dec'] >= dec_max:
        # For SALT we don't want anything with declination +10 or above.
        return False
    
    if not has_recent_nondetection(entry, 
                                   N_days = N_days,
                                    N_nondet_min=N_nondet_min):
        return False
    
    if not has_non_w_detection(entry):
        return False

    if not is_not_too_old(entry, N_span_days=N_span_days):
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



def _fetch_custom_list_ids(objectgroupid):
    """Grab the list of ATLAS objects in a custom list - it's used a few times
    so abstracted away to make the main pipeline functions cleaner to read

    Returns
    -------
    SET of ATLAS IDs
    """
    result = ac.RequestCustomListsTable({'objectgroupid': objectgroupid}, get_response=True)

    if not result.response_data:
        return set()
    
    df = pd.DataFrame(result.response_data).drop('object_group_id', axis=1)
    return set(df.transient_object_id.values.astype(str))


def clean_up(N_days=SALT_FRESHNESS_DAYS,
             N_nondet_min=SALT_NONDET_CLUSTER_MIN,
             N_span_days=SALT_MAX_SPAN_DAYS):
    """Finds ATLAS IDs to be cleaned up from SALT list (classified, garbage, or stale)

    Returns
    --------
    list of ATLAS IDs to be removed from SALT list
    """

    try:
        logging.info("Fetching SALT list (objectgroupid=14)...")
        salt_ids = _fetch_custom_list_ids(14)

        if not salt_ids:
            logging.info("SALT list is empty - nothing to clean.")
            return []

        logging.info(f"Fetched {len(salt_ids)} entries from SALT list.")

        try:
            logging.info("Requesting source data for SALT members...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=np.array(list(salt_ids)),
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

                # 0=garbage, 5=attic, 11=pm_stars (HPM)
                if classification is not None or detection_list_id in (0, 5, 11):  
                    to_remove.append(atlas_id)

                # If latest non detections too old, not ineteresting to us.
                elif not has_recent_nondetection(entry,
                                                 N_days=N_days,
                                                N_nondet_min=N_nondet_min):
                    to_remove.append(atlas_id)
                # Check that the lightcurve is not too old 
                elif not is_not_too_old(entry, N_span_days=N_span_days):
                    to_remove.append(atlas_id)

            except Exception:
                logging.exception("Error processing SALT member entry.")

        return to_remove

    except Exception:
        logging.exception("Failed to fetch SALT list.")
        raise


def fill_up(dec_max=SALT_DEC_MAX,
            N_days=SALT_FRESHNESS_DAYS,
            N_nondet_min=SALT_NONDET_CLUSTER_MIN,
            N_span_days=SALT_MAX_SPAN_DAYS,
            db_path=None):
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
        salt_ids_set = _fetch_custom_list_ids(14)
        logging.info(f"{len(salt_ids_set)} objects currently in SALT list.")

        logging.info("Fetching IDs previously observed & removed from SALT list...")
        removed_ids_set = set(str(id_) for id_ in db.get_removed_atlas_ids_for_list('SALT', db_path=db_path))
        logging.info(f"{len(removed_ids_set)} objects previously observed & removed - excluded from re-add.")

        logging.info("Fetching follow_up list (dec-filtered at the API level)...")
        follow_up = ac.RequestATLASIDsFromWebServerList(list_name='follow_up', dec_lte=dec_max)
        follow_up_ids = set(follow_up.atlas_id_list_str)
        logging.info(f"Fetched {len(follow_up_ids)} entries from follow_up list.")

        logging.info("Fetching Southern 100Mpc Transients list (objectgroupid=2)...")
        mookodi_ids = _fetch_custom_list_ids(2)
        logging.info(f"Fetched {len(mookodi_ids)} entries from Southern 100Mpc Transients list.")

        candidate_ids = np.array([
            id_ for id_ in (follow_up_ids | mookodi_ids)
            if id_ not in salt_ids_set and id_ not in removed_ids_set
        ])
        logging.info(f"{len(candidate_ids)} candidates not already in SALT list or previously removed.")

        if len(candidate_ids) == 0:
            logging.info("No new candidates to evaluate.")
            return [], {}

        try:
            logging.info("Requesting source data for SALT candidates...")
            multi_data = ac.RequestMultipleSourceData(
                array_ids=candidate_ids,
                mjdthreshold=61_000,
                chunk_size=25
            )
            multi_data.chunk_get_response_quiet()
            logging.info(f"Received data for {len(multi_data.response_data)} sources.")
        except Exception:
            logging.exception("Error fetching source data for SALT candidates.")
            raise

        to_add = []
        vra_scores = {}
        for entry in multi_data.response_data:
            try:
                #  CALLING SPECIAL FUNCTION WHERE ADDING LOGIC LIVES
                # ################################################## #
                if should_add_to_salt(entry, dec_max=dec_max,
                                      N_days=N_days,
                                      N_nondet_min=N_nondet_min,
                                      N_span_days=N_span_days):
                    atlas_id = entry['object']['id']
                    to_add.append(atlas_id)
                    vra_scores[str(atlas_id)] = entry['object'].get('vra')

            except Exception:
                logging.exception("Error processing SALT candidate entry.")

        return to_add, vra_scores

    except Exception:
        logging.exception("Failed to process input lists for SALT candidates.")
        raise


if __name__ == "__main__":
    to_remove = clean_up()
    remove_targets_from_list(to_remove, list_name='salt')
    db.log_removed(to_remove, 'bk_young_not_fast_track')

    to_add, vra_scores = fill_up()
    add_targets_to_list(to_add, list_name='salt')
    db.log_added(to_add, 'bk_young_not_fast_track', vra_scores=vra_scores)
