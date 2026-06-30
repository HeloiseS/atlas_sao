# Claude wrote this for xtgal_3mnths cache refresh (2026-06-30)
from datetime import datetime, timedelta
import atlasapiclient.client as ac
import atlas_sao.db as db
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

N_MONTHS = 3


def refresh(n_months=N_MONTHS, db_path=None):
    cutoff = (datetime.now() - timedelta(days=30 * n_months)).strftime('%Y-%m-%d')
    logging.info(f"Fetching VRA scores since {cutoff}...")

    vra = ac.RequestVRAScores({'datethreshold': cutoff}, get_response=True)

    if not vra.response_data:
        logging.info("No VRA scores returned.")
        return

    logging.info(f"Received {len(vra.response_data)} VRA score entries.")
    entries = [(row['transient_object_id_id'], row['preal']) for row in vra.response_data]

    db.upsert_xtgal(entries, db_path=db_path)
    db.deactivate_before(cutoff, db_path=db_path)
    logging.info(f"xtgal_3mnths refreshed. Deactivated entries before {cutoff}.")


if __name__ == "__main__":
    refresh()
