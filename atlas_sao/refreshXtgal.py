# Claude wrote this for xtgal_3mnths cache refresh (2026-06-30)
# HFS Reviewed 2026-07-01 - docstrings comments 
from datetime import datetime, timedelta
import atlasapiclient.client as ac
import atlas_sao.db as db
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

N_WEEKS = 6


def refresh(n_weeks=N_WEEKS, db_path=None):
    """
    Checks the VRA Scores table to add new alerts we don't have yet and deactivates old ones
    """

    # Cutoff data 
    cutoff = (datetime.now() - timedelta(days=7 * n_weeks)).strftime('%Y-%m-%d')

    ### Get VRA Scores table 
    logging.info(f"Fetching VRA scores since {cutoff}...")
    vra = ac.RequestVRAScores({'datethreshold': cutoff}, get_response=True)

    if not vra.response_data:
        logging.info("No VRA scores returned.")
        return

    logging.info(f"Received {len(vra.response_data)} VRA score entries.")

    # HFS: For each row, if the username is not none (so it was a human decision)
    # and we have preal == 1 and pgal == 0, then we have a Good or Follow up target
    # which is what we want to keep track of. 
    atlas_ids = list({
        row['transient_object_id']
        for row in vra.response_data
        if row['username'] is not None and row['preal'] == 1.0 and row['pgal'] == 0.0
    })
    logging.info(f"Filtered to {len(atlas_ids)} unique human-labeled extragalactic transients.")

    db.upsert_xtgal(atlas_ids, db_path=db_path)
    db.deactivate_old_alerts(cutoff, db_path=db_path)
    logging.info(f"xtgal_3mnths refreshed. Deactivated entries before {cutoff}.")


if __name__ == "__main__":
    refresh()
