# 2026-08-18: First write. Claude written, HFS Reviewed and Commented
# Cleans up the lists after the slack reports of Observations
# have come in, so we don't send for trigger the same object twice

import numpy as np
import atlasapiclient.client as ac
import logging
import atlas_sao.db as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)


# Maps the name of the lists in the db (keys) to the name of lists
# recognised by atlasapiclient (values)
# NOTE: will need updating when/if we start using salt list again
RELATED_LIST_TO_LIST_NAME = {
    '100Mpc Southern Transients': 'south_transients_100mpc',
    'Bright 100Mpc Southern Transients': 'bright_south_transients_100mpc',
    'Southern Transients at Peak': 'south_transients_peak',
}

# Maps the atlasapiclent list names to the names of the 
# book keeping tables in our sqlite database
# NOTE: will need updating when/if we start using salt list again
LIST_NAME_TO_BK_TABLE = {
    'bright_south_transients_100mpc': 'bk_young_fast_track',
    'south_transients_peak': 'bk_peak',
    'salt': 'bk_young_not_fast_track',
}


"""
HFS: REMOVED
    At time of writing, we have deprecated the salt list so it doesn't appear
    in the related_lists in the slack_messages table. 
    There is therefore NO ACTION expected at this point in time on the salt list
    If/When we start using the salt list again, we should ALWAYS use the 
    related_list mentioned in the messages, not try to guess based on telescopes
    as over time we may develop several lists for SALT. 

def resolve_list_name(telescope, 
                      related_list):



    if related_list is not None:
        return RELATED_LIST_TO_LIST_NAME.get(related_list)
    if telescope == 'SALT':
        return 'salt'
    return None
"""

def remove_targets_from_list(array_ids, 
                             list_name: str, 
                             chunk_size: int = 25):
    """Removes ATLAS_IDs from the ATLAS Transient Name server list of choice"""
    if len(array_ids) == 0:
        return
    
    logging.info(f"Removing {len(array_ids)} targets from '{list_name}'...")
    ac.RemoveFromCustomList(array_ids=np.array(array_ids), list_name=list_name, chunk_size=chunk_size)


def process_observed_reports(db_path=None):
    """Process reports of observations (found in database)"""

    # 1. Grab the report rows where Status = Observed and list_removed_at = NULL
    reports = db.get_unprocessed_observed_reports(db_path=db_path)
    if not reports:
        logging.info("No unprocessed 'Observed' reports.")
        return

    logging.info(f"Found {len(reports)} unprocessed 'Observed' reports.")

    atlas_ids_by_list = {}
    row_ids_by_list = {}

    # 2. Read each observation report and record the atlas ids that need to be 
    #    removed for each list  as well as which row id (in slack_messages)
    #    is concerned (so we can update the list_removed_at column later)
    for report in reports:
        #list_name = resolve_list_name(report['telescope'], report['related_list'])
        
        # Use our mapping to get the atlasapiclient list name
        list_name = RELATED_LIST_TO_LIST_NAME.get(report['related_list'])

        if list_name is None:
            logging.warning(
                f"Could not resolve list for 'Observed' report id={report['id']} "
                f"related_list={report['related_list']!r} "
                f"atlas_id={report['atlas_id']} - skipping, left for manual review."
            )
            continue

        # NOTE: On the syntax, this is equivalent to
        # if list_name not in atlas_ids_by_list:
        #     atlas_ids_by_list[list_name] = []
        # atlas_ids_by_list[list_name].append(report['atlas_id'])
        atlas_ids_by_list.setdefault(list_name, []).append(report['atlas_id'])
        row_ids_by_list.setdefault(list_name, []).append(report['id'])

    # 3. For each list (key) and list of atlas_ids (value) in our dictionary 
    for list_name, atlas_ids in atlas_ids_by_list.items():

        ## 3.1 Clean up the List in the Web Server

        # make sure we have a unique list of ATLAS_IDs
        unique_ids = sorted(set(atlas_ids))
        try:
            # check size not zero and do some logging. If function fails log that too below
            remove_targets_from_list(unique_ids, list_name=list_name)
        except Exception:
            logging.exception(f"Failed to remove {unique_ids} from '{list_name}' - leaving reports unprocessed for retry.")
            continue

        ## 3.2 Update our book keeping table so it's in sync with web server list

        ### 3.2.1 If it's the Peak List we also need to update the ACTIVE flag in xtgal_watchlist
        ###       which is the input source of the Peak list. (Otherwise we'll get alerts coming BACK)
        if list_name == 'south_transients_peak':
            db.deactivate_xtgal_ids(unique_ids, db_path=db_path)

        ### 3.2.2 For all lists we update the relevant book keeping table
        bk_table = LIST_NAME_TO_BK_TABLE.get(list_name)

        if bk_table:
            db.log_removed(unique_ids, bk_table, db_path=db_path)

        ## 3.3 Now update the list_removed_at in the slack_messages table
        #      so won't get reprocessed. 

        for row_id in row_ids_by_list[list_name]:
            db.mark_list_removed(row_id, db_path=db_path)


if __name__ == "__main__":
    process_observed_reports()
