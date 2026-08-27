"""
ATLAS API code supplied by Ken Smith (QUB/Oxford) and modified and appended in
December 2024 for the SAAO IO project.

Aug 2026: OCS / Mookodi variant (runs from its own cronjob, alongside the SALT
listener).
  - listens on ATLAS custom list 16 ("Bright 100Mpc Southern Transients") 
    from Heloise Stevance's (QUB/Oxford) VRA
  - submits Mookodi SPECTROSCOPY observing requests to the SAAO OCS via aeonlib
    (SAAOFacility.submit_request_group)
  - only triggers on targets brighter than mag 17.5; exposure time scales with
    the latest ATLAS magnitude
  - observing window is "now -> next Sutherland sunrise"; the OCS scheduler is
    responsible for rejecting anything not actually visible
  - downloads the ATLAS triplet postage stamps (target/ref/diff) per object

@author: Nic Erasmus @ SAAO
"""


from datetime import datetime, timedelta
from astropy.time import Time, TimeDelta
import os
import re
import argparse
import requests
import json
from astropy.io import ascii
from astropy.coordinates import SkyCoord
from astropy import units as u
from PIL import Image, ImageDraw, ImageFont
from astroquery.skyview import SkyView
import numpy as np

# OCS / Mookodi observing-request submission via aeonlib.
from aeonlib.conf import Settings
from aeonlib.models import SiderealTarget, Window
from aeonlib.ocs import Constraints, Location, Request, RequestGroup
from aeonlib.ocs.saao.facility import SAAOFacility
from aeonlib.ocs.saao.instruments import SAAO1M0AMookodiSpec

# Sunrise calculation for the observing window (astropy; no saltshaker dependency).
from astropy.coordinates import EarthLocation, AltAz, get_sun

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("LOG.log"),
        logging.StreamHandler()
    ]
)

# Load the JSON file with all keys
with open('key.json', 'r') as file:
    keys = json.load(file)

#######################################
### People to send email alerts to: ###
### (now stored in key.json under "email_addresses", e.g.
###   "email_addresses": ["nerasmus@saao.ac.za", "sndwe@dtu.dk"])
#######################################
email_addresses = keys.get("email_addresses", [])
if not email_addresses:
    logging.warning(
        'No "email_addresses" found in key.json - no email alerts will be sent.'
    )
#######################################

##################################################
### OCS / Mookodi submission config (aeonlib): ###
##################################################
# The OCS token lives in key.json under "IO_OCS_token". aeonlib reads its
# credentials from a Settings object; we build one explicitly from key.json so
# this script doesn't depend on environment variables or a .env file.
OCS_API_ROOT = 'https://ocsio.saao.ac.za/api/'

# The OCS portal page for a submitted request group is
#   {OCS_REQUESTGROUP_URL}{id}
# where {id} is the id returned by the OCS on submission (submitted.id).
OCS_REQUESTGROUP_URL = 'https://ocsio.saao.ac.za/requestgroups/'

# Proposal awarded time on Mookodi. Stored in key.json under "IO_OCS_proposal_id"
# so all OCS config lives in one place.
OCS_PROPOSAL_ID = keys.get("IO_OCS_proposal_id", "")
if not OCS_PROPOSAL_ID:
    logging.warning(
        'No "IO_OCS_proposal_id" in key.json - OCS submissions will fail.'
    )

# aeonlib Settings populated from key.json (saao_token -> IO_OCS_token).
OCS_SETTINGS = Settings(
    saao_token=keys.get("IO_OCS_token", ""),
    saao_api_root=OCS_API_ROOT,
)
if not keys.get("IO_OCS_token"):
    logging.warning(
        'No "IO_OCS_token" in key.json - OCS submissions will fail auth.'
    )

# Sutherland (SAAO) site, for the "now -> next sunrise" observing window.
SUTHERLAND = EarthLocation(lat=-32.379444 * u.deg,
                           lon=20.810556 * u.deg,
                           height=1798 * u.m)

# Only trigger on targets at least this bright (latest ATLAS mag). Anything
# fainter is skipped before any request is built.
MAG_LIMIT = 17.5

# Mookodi SPEC exposure time (seconds) as a function of latest ATLAS magnitude.
# For now: a flat 600 s, stepping up to 900 s only for faint targets. Targets
# fainter than MAG_LIMIT never reach here.
def mookodi_exposure_time(mag):
    """Spectroscopic exposure time (s) from the latest ATLAS magnitude."""
    if mag < 17.0:
        return 600
    else:                 # 17.0 <= mag <= 17.5
        return 900

# Follow-up griz imaging taken after the spectrum: filters and per-filter
# exposure time (s). Edit this list to change which bands (e.g. drop "z'" for
# gri only, or reorder). Each becomes its own Mookodi imaging instrument_config
# with the slit and grism taken out of the beam.
GRIZ_IMAGING_FILTERS = ["g'", "r'", "i'", "z'"]
GRIZ_IMAGING_EXPTIME = 60
##################################################

#########################################################
### ATLAS transient credentials and site information: ###
#########################################################
ATLAS_HEADER = {'Authorization': 'Token ' + keys.get("atlas_token")}
ATLAS_URL = 'https://psweb.mp.qub.ac.uk/sne/atlas4/api/'

# The ATLAS Transient Server candidate page for an object is
#   {ATLAS_CANDIDATE_URL}{id}/
# where {id} is the 19-digit numeric object id (target['id']).
ATLAS_CANDIDATE_URL = 'https://star.pst.qub.ac.uk/sne/atlas4/candidate/'

# Which ATLAS custom list this script listens on, and its human-readable name.
# The objectlist/ API returns the objects on the list but NOT the list's name,
# so we map the id -> name locally. TRIGGER_SOURCE (below) is derived from this.
ATLAS_LIST_ID = 16
ATLAS_LIST_NAMES = {
    2: "100Mpc Southern Transients",
    16: "Bright 100Mpc Southern Transients",
    17: "Southern Transients at Peak",
}
TRIGGER_SOURCE = ATLAS_LIST_NAMES.get(ATLAS_LIST_ID, f"list {ATLAS_LIST_ID}")

# Trigger metadata included in the email/Slack alerts.
#   STATUS : Triggered | Observed | Aborted  (this script only submits, so "Triggered")
#   NOTES  : free text; "None" for now.
TRIGGER_STATUS = "Triggered"
TRIGGER_NOTES = "None"

# Postage-stamp jpegs live on the QUB image server. A full URL is
#   {host}{mjd}/{stem}_{target|ref|diff}.jpeg
# where stem (the "discovery_target") looks like
#   1115237410164431900_61184.265_01a61184o0066o_210
# and {mjd} is derived from characters 3-7 of the exposure id inside the stem
# (e.g. exposure id '01a61184o' -> '61184'). The two hosts below are
# interchangeable mirrors; we try them in order.
ATLAS_STAMP_HOSTS = [
    'https://star.pst.qub.ac.uk/sne/atlas4/media/images/data/atlas4/',
    'https://psweb.mp.qub.ac.uk/sne/atlas4/media/images/data/atlas4/',
]

# ATLAS discovery triplet postage stamps are 200x200 px at ~1.86 arcsec/pixel,
# i.e. 6.2 arcmin on a side (Smith et al. 2020, ATLAS Transient Science Server).
# The DSS2 finder chart is pulled at this same size so the panels share a field
# of view (the old DSS2 cutout was 5 arcmin, ~20% smaller than the ATLAS stamps).
ATLAS_STAMP_FOV_ARCMIN = 6.2

#############################################
### Where image files (and the per-object debug JSON) get written, so they
### don't clutter the repo root. Everything image-related goes in here.
#############################################
IMAGE_DIR = os.path.join(os.getcwd(), "stamps")
os.makedirs(IMAGE_DIR, exist_ok=True)


def img_path(filename):
    """Full path inside the image output directory for a given filename."""
    return os.path.join(IMAGE_DIR, filename)

#----------------------------------------------------------------------------------


def send_email(message, email_to, subject, target_names, html_message=None):

    gmail_user = 'aio.saao2020@gmail.com'
    gmail_p = keys.get("gmail_pass")

    # Email details
    fromx = gmail_user
    to = email_to
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = "SAAO IO"
    msg['To'] = ", ".join(to)

    # Email body. When an HTML version is supplied we send a multipart/alternative
    # so clients that can render HTML show the nicely laid-out table (columns can't
    # misalign and the TNS/ATLAS URLs become real hyperlinks), while text-only
    # clients fall back to the plain-text block layout. The alternative part must
    # be nested inside the outer mixed multipart that also carries the image
    # attachments, and the plain part comes first (least-preferred -> most).
    if html_message:
        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText(message, 'plain'))
        alt.attach(MIMEText(html_message, 'html'))
        msg.attach(alt)
    else:
        msg.attach(MIMEText(message, 'plain'))

    # Attach the single combined stamp image per target: {name}_stamps.jpeg
    # (the individual DSS2 .png and ATLAS *_target/ref/diff.jpeg files are still
    #  saved to disk, so they remain available/downloadable.)
    images_to_attach = []
    for name in target_names:
        if name is None:
            continue
        safe = name.replace(' ', '_')
        images_to_attach.append(img_path(f"{safe}_stamps.jpeg"))

    logging.info(f"Attempting to attach: {images_to_attach}")

    # Attach each file that actually exists on disk
    for image_path in images_to_attach:
        if not os.path.exists(image_path):
            continue
        try:
            with open(image_path, 'rb') as attachment_file:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment_file.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={os.path.basename(image_path)}'
                )
                msg.attach(part)
        except Exception as err:
            logging.error(f'Error attaching file {image_path}: {err}')

    # Send the email
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.ehlo()
        server.login(gmail_user, gmail_p)
        server.sendmail(fromx, to, msg.as_string())
        server.quit()
        logging.info('Email sent!')
    except Exception as err:
        logging.error('Something went wrong with sending emails...')
        logging.error((Exception, err))


def _slack_blocks(records):
    """
    Build Block Kit blocks from the structured per-target records so the Slack
    post reads cleanly on any screen width (instead of a wide fixed-width table
    that wraps badly). One section per target with the key fields as short
    label/value lines, plus a divider between targets.

    Slack allows at most 50 blocks per message, so if there are many targets we
    chunk the caller side; here we just emit blocks for whatever we're given.
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🔭 ATLAS Transient OCS (Mookodi) requests"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*{len(records)}* new Mookodi spectroscopy request(s) submitted to the OCS"}
            ],
        },
        {"type": "divider"},
    ]

    for r in records:
        # Compact summary of the submitted observing window.
        win_text = f"  • {r['window_start']} → {r['window_end']} UTC (now → next sunrise)"

        xmatch = (f"<{r['crossmatch_link']}|TNS>"
                  if r["crossmatch_link"] != "NA" else "NA")
        atlas_page = (f"<{r['atlas_link']}|ATLAS candidate>"
                      if r.get("atlas_link", "NA") != "NA" else "NA")

        # *bold* labels, values after. Grouped into a couple of fields columns
        # (Slack renders "fields" as a responsive 2-column grid).
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{r['name']}*   ·   {r['sherlock']}   ·   {atlas_page}"},
            "fields": [
                {"type": "mrkdwn", "text": f"*ATLAS ID*\n{r['atlas_id']}"},
                {"type": "mrkdwn", "text": f"*Status*\n{r['status']}"},
                {"type": "mrkdwn", "text": f"*RA / Dec*\n{r['ra']:.5f}, {r['dec']:.5f}"},
                {"type": "mrkdwn", "text": f"*Exposure*\n{r['exp_time']}s spec + {r['griz']} imaging"},
                {"type": "mrkdwn", "text": f"*Disc. mag / date*\n{r['disc_mag']:.2f} · {r['disc_date']} UT"},
                {"type": "mrkdwn", "text": f"*Latest*\n{r['latest_mag']:.2f} {r['latest_filter']} · {r['latest_date']} UT"},
                {"type": "mrkdwn", "text": f"*Trigger source*\n{r['trigger_source']}"},
                {"type": "mrkdwn", "text": f"*Notes*\n{r['notes']}"},
                {"type": "mrkdwn", "text": f"*OCS request id*\n<{r['ocs_link']}|{r['ocs_id']}>"},
                {"type": "mrkdwn", "text": f"*Crossmatch*\n{xmatch}"},
            ],
        })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Observing window (UTC)*\n{win_text}"}],
        })
        blocks.append({"type": "divider"})

    return blocks


def send_slack(records, target_names):
    """
    Post the alert to a Slack channel in parallel with the email.

    Requires two entries in key.json:
        "slack_bot_token": "xoxb-..."   (a bot token with chat:write and,
                                          for image uploads, files:write)
        "slack_channel":   "C0123456789" (channel ID, or "#channel-name")

    The alert is posted as Block Kit sections (one tidy block per target) rather
    than a wide monospace table, so it reads well on Slack including mobile. Each
    target's combined {name}_stamps.jpeg is then uploaded to the same channel.
    Missing images are skipped. Any failure is logged but never raised, so a
    Slack problem can't stop the email path (or vice versa).
    """
    slack_token = keys.get("slack_bot_token")
    slack_channel = keys.get("slack_channel")

    if not slack_token or not slack_channel:
        logging.warning(
            'Slack not configured (need "slack_bot_token" and "slack_channel" '
            'in key.json) - skipping Slack notification.'
        )
        return

    headers = {"Authorization": f"Bearer {slack_token}"}

    # 1) Post the alert as Block Kit. A fallback "text" is included for
    #    notifications/screen-readers. Slack caps a message at 50 blocks, so we
    #    send in chunks of targets if needed (header only on the first chunk).
    try:
        # ~3 blocks per target + 3 header blocks; keep well under 50.
        per_chunk = 14  # targets per message
        fallback = f"ATLAS Transient OCS (Mookodi) requests: {len(records)} new target(s)"
        if not records:
            chunks = [[]]
        else:
            chunks = [records[i:i + per_chunk] for i in range(0, len(records), per_chunk)]

        for ci, chunk in enumerate(chunks):
            blocks = _slack_blocks(chunk)
            if ci > 0:
                # Drop the header/context on continuation messages.
                blocks = [b for b in blocks if b["type"] not in ("header", "context")][:]
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers=headers,
                json={
                    "channel": slack_channel,
                    "text": fallback,      # fallback for notifications
                    "blocks": blocks,
                },
                timeout=30,
            )
            payload = resp.json()
            if not payload.get("ok"):
                logging.error(f"Slack chat.postMessage failed: {payload.get('error')}")
            else:
                logging.info("Slack message sent!")
    except Exception as err:
        logging.error("Something went wrong posting the Slack message...")
        logging.error((Exception, err))

    # 2) Upload each target's combined stamp using the modern
    #    files.getUploadURLExternal -> upload -> files.completeUploadExternal flow
    #    (files.upload is deprecated/disabled on newer Slack apps).
    for name in target_names:
        if name is None:
            continue
        safe = name.replace(' ', '_')
        image_path = img_path(f"{safe}_stamps.jpeg")
        if not os.path.exists(image_path):
            continue
        try:
            length = os.path.getsize(image_path)
            filename = os.path.basename(image_path)

            # (a) Reserve an upload URL.
            g = requests.post(
                "https://slack.com/api/files.getUploadURLExternal",
                headers=headers,
                data={"filename": filename, "length": length},
                timeout=30,
            ).json()
            if not g.get("ok"):
                logging.error(f"Slack getUploadURLExternal failed for {name}: {g.get('error')}")
                continue
            upload_url = g["upload_url"]
            file_id = g["file_id"]

            # (b) PUT the bytes to the reserved URL.
            with open(image_path, "rb") as fh:
                put = requests.post(upload_url, data=fh.read(), timeout=60)
            if put.status_code != 200:
                logging.error(f"Slack file upload PUT failed for {name}: HTTP {put.status_code}")
                continue

            # (c) Complete the upload and share it into the channel.
            c = requests.post(
                "https://slack.com/api/files.completeUploadExternal",
                headers=headers,
                json={
                    "files": [{"id": file_id, "title": f"{name} stamps"}],
                    "channel_id": slack_channel,
                },
                timeout=30,
            ).json()
            if not c.get("ok"):
                logging.error(f"Slack completeUploadExternal failed for {name}: {c.get('error')}")
            else:
                logging.info(f"Slack stamp uploaded for {name}")
        except Exception as err:
            logging.error(f"Error uploading Slack image for {name}: {err}")


def next_sutherland_sunrise(t_start=None):
    """
    Return the next sunrise at Sutherland as an astropy Time, searching forward
    from t_start (default: now). Sunrise = solar altitude crossing 0 deg upward.
    Falls back to t_start + 12 h if the search fails, so a request can still go
    out (the OCS will reject anything not actually observable).
    """
    if t_start is None:
        t_start = Time.now()
    try:
        # Sample solar altitude on a fine grid over the next 24 h and find the
        # first upward zero-crossing (night -> day).
        dt = np.arange(0, 24 * 60 + 1, 5)  # minutes, 0..1440 step 5
        times = t_start + TimeDelta(dt * 60.0, format='sec')
        altaz = AltAz(obstime=times, location=SUTHERLAND)
        alt = get_sun(times).transform_to(altaz).alt.deg
        for i in range(1, len(alt)):
            if alt[i - 1] < 0.0 <= alt[i]:
                # Linear interpolation between the two bracketing samples.
                frac = (0.0 - alt[i - 1]) / (alt[i] - alt[i - 1])
                return times[i - 1] + (times[i] - times[i - 1]) * frac
    except Exception as err:
        logging.error(f"sunrise calculation failed: {err}")
    return t_start + TimeDelta(12 * 3600, format='sec')


def send_observing_request_to_OCS(name, mag, ra_deg, dec_deg, window_start, window_end):
    """
    Build and submit a Mookodi SPECTROSCOPY observing request to the SAAO OCS
    via aeonlib. Returns the SubmittedRequestGroup on success.

    Exposure time scales with `mag` (see mookodi_exposure_time). The observing
    window is [window_start, window_end] (now -> next Sutherland sunrise); the
    OCS scheduler decides real visibility and rejects anything unobservable.

    Raises on validation or submission failure so the caller can log and skip.
    """
    exp_time = mookodi_exposure_time(mag)

    target = SiderealTarget(
        name=name[:50],           # OCS caps target name at 50 chars
        type="ICRS",
        ra=float(ra_deg),
        dec=float(dec_deg),
    )

    # Mookodi long-slit spectroscopy configuration, followed by griz imaging.
    # All instrument_configs share one configuration (same target/acquisition/
    # guiding); the OCS executes them in order, so the spectrum runs first and
    # the imaging afterwards. For imaging we take the slit and grism OUT of the
    # beam and put the science filter IN (obfilter out). All values validate
    # against the aeonlib enums.
    instrument_configs = [
        # 1) The spectrum.
        SAAO1M0AMookodiSpec.config_class(
            exposure_count=1,
            exposure_time=exp_time,
            mode="1x1HighSlowAuto",
            optical_elements=SAAO1M0AMookodiSpec.optical_elements_class(
                filter="out", obfilter="OrdBlck_Fltr", slit="mk-wide", grism="in",
            ),
        ),
    ]
    # 2) One imaging exposure per griz filter (slit/grism out, filter in).
    for img_filter in GRIZ_IMAGING_FILTERS:
        instrument_configs.append(
            SAAO1M0AMookodiSpec.config_class(
                exposure_count=1,
                exposure_time=GRIZ_IMAGING_EXPTIME,
                mode="1x1HighSlowAuto",
                optical_elements=SAAO1M0AMookodiSpec.optical_elements_class(
                    filter=img_filter, obfilter="out", slit="out", grism="out",
                ),
            )
        )

    config = SAAO1M0AMookodiSpec(
        type="EXPOSE",
        target=target,
        constraints=Constraints(max_airmass=1.8),
        instrument_configs=instrument_configs,
        acquisition_config=SAAO1M0AMookodiSpec.acquisition_config_class(
            mode="AcN:OFF&Acq:ON",
        ),
        guiding_config=SAAO1M0AMookodiSpec.guiding_config_class(
            mode="GUIDE ON", optional=True,
        ),
    )

    request_group = RequestGroup(
        name=name[:50],
        proposal=OCS_PROPOSAL_ID,
        observation_type="NORMAL",
        operator="SINGLE",
        ipp_value=1.05,
        requests=[
            Request(
                location=Location(telescope_class="1m0"),
                configurations=[config],
                windows=[Window(start=window_start.to_datetime(),
                                end=window_end.to_datetime())],
                observation_note=f"ATLAS transient {name}, mag {mag:.2f}, "
                                 f"{exp_time}s Mookodi spectrum + "
                                 f"{GRIZ_IMAGING_EXPTIME}s "
                                 f"{''.join(f[0] for f in GRIZ_IMAGING_FILTERS)} imaging",
            )
        ],
    )

    facility = SAAOFacility(settings=OCS_SETTINGS)

    # Pre-validate so bad requests fail loudly with the OCS's own error messages
    # rather than a bare HTTP error on submit.
    valid, errors = facility.validate_request_group(request_group)
    if not valid:
        raise RuntimeError(f"OCS validation failed for {name}: {errors}")

    submitted = facility.submit_request_group(request_group)
    logging.info(
        f"OCS Mookodi request submitted for {name}: "
        f"id={submitted.id}, state={submitted.state}, exp={exp_time}s"
    )
    return submitted


def download_atlas_stamps(atlas_id, name, target=None):
    """
    Download the ATLAS discovery triplet postage stamps (target / reference /
    difference) for an object and save them as:
        {name}_ATLAS_target.jpeg
        {name}_ATLAS_ref.jpeg
        {name}_ATLAS_diff.jpeg

    A full stamp URL is {host}{mjd}/{stem}_{target|ref|diff}.jpeg, where the
    three images share one "stem" (the discovery_target) and {mjd} comes from
    characters 3-7 of the exposure id embedded in the stem.

    Stem resolution order:
      1. the objectlist record we already have (no extra API call), then
      2. the single-object /objects/ endpoint (also dumped to
         "{name}_atlas_object.json" for debugging).
    The earliest-MJD stem is used (= the discovery image).
    """
    saved = []
    safe = name.replace(' ', '_')

    # --- 1) Resolve the stamp stem ---------------------------------------
    stems = []

    # (a) cheapest: it may already be in the objectlist record.
    if target is not None:
        stems = _find_stamp_stems(target)
        if stems:
            logging.info(f"{name}: stamp stem found in objectlist record")

    # (b) otherwise ask the single-object endpoint.
    if not stems:
        atlas_id = str(atlas_id)
        if not (atlas_id.isdigit() and len(atlas_id) == 19):
            logging.error(
                f"ATLAS stamps for {name}: '{atlas_id}' is not a 19-digit id. "
                f"Pass target['id'] (the numeric object id), not the designation."
            )
            return saved
        try:
            # NOTE: the objects/ endpoint expects the lower MJD threshold under
            # the key 'mjd' (confirmed from the official atlasapiclient source).
            r = requests.post(
                ATLAS_URL + 'objects/',
                {'objects': atlas_id, 'mjd': 0},
                headers=ATLAS_HEADER,
            )
            logging.info(f"objects/ query for {name} ({atlas_id}) -> HTTP {r.status_code}")
            if r.status_code != 200:
                logging.error(f"objects/ query failed for {name}: {r.text[:300]}")
                return saved
            obj = r.json()
            obj = obj[0] if isinstance(obj, list) and obj else obj
            with open(img_path(f"{safe}_atlas_object.json"), "w") as fh:
                json.dump(obj, fh, indent=2)
            stems = _find_stamp_stems(obj)
            if not stems:
                # No assembled stem in the feed (discovery_target null). The
                # postage stamps live in a DB table the API doesn't expose, but
                # we can rebuild a stamp filename from a lightcurve detection
                # and confirm it exists on the image server.
                try:
                    top_keys = list(obj.keys()) if isinstance(obj, dict) else type(obj).__name__
                    lc = obj.get('lc') if isinstance(obj, dict) else None
                    lc_keys = list(lc[0].keys()) if isinstance(lc, list) and lc else None
                    logging.info(
                        f"{name}: no assembled stem (discovery_target null). "
                        f"Top keys: {top_keys}; lc[0] keys: {lc_keys}"
                    )
                except Exception:
                    pass
                rebuilt = _stem_from_lc_verified(obj, atlas_id, name)
                if rebuilt:
                    stems = [rebuilt]
        except Exception as err:
            logging.error(f"Could not retrieve object JSON for {name}: {err}")
            return saved

    if not stems:
        logging.error(
            f"No stamp available for {name}: 'discovery_target' is null in the "
            f"ATLAS feed and no lightcurve detection produced a stamp URL that "
            f"resolved on the image server. Skipping stamps for this object."
        )
        return saved

    # Discovery = earliest detection MJD (2nd underscore field of the stem).
    def _stem_mjd(s):
        try:
            return float(s.split('_')[1])
        except Exception:
            return float('inf')
    stem = sorted(stems, key=_stem_mjd)[0]
    logging.info(f"Using ATLAS stem for {name}: {stem}")

    # --- 2) Download each type, trying both hosts ------------------------
    for label in ('target', 'ref', 'diff'):
        filename = img_path(f"{safe}_ATLAS_{label}.jpeg")
        for host in ATLAS_STAMP_HOSTS:
            stamp_url = build_atlas_stamp_urls(stem, host)[label]
            try:
                img = requests.get(stamp_url, headers=ATLAS_HEADER, timeout=30)
                logging.info(f"GET {label} -> HTTP {img.status_code} ({stamp_url})")
                if img.status_code == 200 and img.content:
                    with open(filename, 'wb') as out:
                        out.write(img.content)
                    saved.append(filename)
                    logging.info(f"Saved ATLAS {label} stamp: {os.path.basename(filename)}")
                    break  # got it; don't try the other host
            except Exception as err:
                logging.error(f"GET {label} from {host} failed: {err}")
        else:
            logging.error(f"Could not download ATLAS {label} stamp for {name} from any host")

    return saved


def _stem_from_lc_verified(obj, objid, name, max_attempts=12):
    """
    When 'discovery_target' is null, rebuild a postage-stamp stem from a
    lightcurve detection and CONFIRM it exists on the image server (the API
    does not expose the stamp table directly).

    A stem is {objid}_{mjd:.3f}_{expname}_{N}. We know objid, and each detection
    gives mjd and expname; the only unknown is the trailing index N. The ATLAS
    stamp pipeline names stamps by detection pixel position, so we try the
    detection's x then y (rounded), newest detection first, and accept the first
    URL that returns HTTP 200. Bounded to max_attempts requests.

    NOTE: if this keeps missing, the exact N field can be pinned in one shot -
    open a stamp on the object's web page, copy its filename, and compare to the
    matching lc detection in the dumped *_atlas_object.json.
    """
    import math
    lc = obj.get('lc') if isinstance(obj, dict) else None
    if not isinstance(lc, list) or not lc:
        return None

    dets = sorted(lc, key=lambda d: d.get('mjd', 0) or 0, reverse=True)  # newest first
    attempts = 0
    for d in dets:
        expname = d.get('expname')
        mjd = d.get('mjd')
        if not expname or mjd is None:
            continue
        mjd_strs = list(dict.fromkeys([f"{mjd:.3f}", f"{math.floor(mjd * 1000) / 1000:.3f}"]))
        n_cands = []
        for key in ('x', 'y'):
            v = d.get(key)
            if v is not None:
                n_cands.append(int(round(v)))
        n_cands = list(dict.fromkeys(n_cands))

        for mjd_str in mjd_strs:
            for N in n_cands:
                stem = f"{objid}_{mjd_str}_{expname}_{N}"
                url = build_atlas_stamp_urls(stem, ATLAS_STAMP_HOSTS[0])['target']
                attempts += 1
                try:
                    r = requests.get(url, headers=ATLAS_HEADER, timeout=20)
                    if r.status_code == 200 and r.content:
                        logging.info(f"{name}: rebuilt stem from lc detection: {stem}")
                        return stem
                except Exception:
                    pass
                if attempts >= max_attempts:
                    logging.info(f"{name}: lc stem rebuild gave up after {attempts} tries")
                    return None
    return None


# A stamp stem looks like: 1115237410164431900_61184.265_01a61184o0066o_210
_STEM_RE = re.compile(r'\d{15,}_\d+\.\d+_\w+_\d+')
# An ATLAS exposure id looks like: 01a61184o  (camera + 'a' + 5-digit MJD + filter)
_EXPID_RE = re.compile(r'\d{2}[a-zA-Z]\d{5}[a-zA-Z]')


def _mjd_dir_from_stem(stem):
    """
    The stamp directory is the integer MJD, taken from characters 3-7 of the
    exposure id embedded in the stem ('01a61184o' -> '61184'). Falls back to the
    integer part of the detection-MJD field if no exposure id is found.
    """
    m = _EXPID_RE.search(stem)
    if m:
        return m.group(0)[3:8]
    try:
        return stem.split('_')[1].split('.')[0]
    except Exception:
        return None


def build_atlas_stamp_urls(stem, host):
    """Given a stem and a host base, return the three triplet jpeg URLs."""
    mjd_dir = _mjd_dir_from_stem(stem)
    base = f"{host}{mjd_dir}/{stem}"
    return {
        'target': f"{base}_target.jpeg",
        'ref':    f"{base}_ref.jpeg",
        'diff':   f"{base}_diff.jpeg",
    }


def _find_stamp_stems(node, found=None):
    """Recursively collect stamp filename stems found anywhere in the JSON."""
    if found is None:
        found = []
    if isinstance(node, dict):
        for value in node.values():
            _find_stamp_stems(value, found)
    elif isinstance(node, list):
        for item in node:
            _find_stamp_stems(item, found)
    elif isinstance(node, str):
        for match in _STEM_RE.findall(node):
            if match not in found:
                found.append(match)
    return found


def download_stamp(coords, name, survey_set='DSS2'):
    """
    Colour-composite finder chart, saved as {name}.png.

    survey_set picks which three bands to pull and how they map to R, G, B.
    The mapping always assigns the REDDEST band to R and the BLUEST to B
    (longer wavelength -> redder channel), which is the physically sensible
    "natural colour" ordering.

    Choosing a survey (southern sky)
    --------------------------------
    These are southern-sky transients, where SDSS has little/no coverage, so for
    most targets 'SDSS' will simply return no data. Prefer:
      'DSS2'  - all-sky, the safe default (used here);
      'PS1'   - Pan-STARRS, deeper, covers dec > ~ -30;
      'SDSS'  - only useful for the small subset of targets in the SDSS footprint.

    The SDSS "mix" you asked about: the standard (Lupton) recipe is
      i -> Red, r -> Green, g -> Blue,
    combined with an asinh stretch (done below) rather than a linear one. Equal
    band weights work well once the asinh stretch + percentile clipping balance
    the dynamic range, so there's no need for the old 0.5/0.75/1.0 fudge factors.
    """
    # (R_band, G_band, B_band) in reddest -> bluest order
    SURVEY_SETS = {
        'DSS2': ["DSS2 IR", "DSS2 Red", "DSS2 Blue"],
        'PS1':  ["PanSTARRS DR1 i", "PanSTARRS DR1 r", "PanSTARRS DR1 g"],
        'SDSS': ["SDSSi", "SDSSr", "SDSSg"],
    }

    def _stretch(data):
        """Percentile-clipped asinh stretch -> floats in [0, 1]."""
        data = np.nan_to_num(np.asarray(data, dtype=float), nan=0.0)
        lo, hi = np.percentile(data, [5.0, 99.5])
        if hi <= lo:
            hi = lo + 1.0
        x = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
        return np.arcsinh(10.0 * x) / np.arcsinh(10.0)

    try:
        # Match the ATLAS postage-stamp field of view so the DSS2 finder lines up
        # with the ATLAS triplet in the combined image (they were mismatched:
        # ATLAS ~1 arcmin vs the old 5 arcmin DSS2 cutout).
        size = ATLAS_STAMP_FOV_ARCMIN * u.arcmin
        surveys = SURVEY_SETS.get(survey_set, SURVEY_SETS['DSS2'])

        # Query SkyView for the three bands (order = R, G, B)
        images = SkyView.get_images(position=coords, survey=surveys, width=size, height=size)
        r_data = images[0][0].data if images[0] else None
        g_data = images[1][0].data if images[1] else None
        b_data = images[2][0].data if images[2] else None

        if r_data is None or g_data is None or b_data is None:
            logging.error(f"One or more {survey_set} bands could not be downloaded. Check coverage at this position.")
        else:
            # Stretch each band and stack into RGB
            rgb_image = np.zeros((r_data.shape[0], r_data.shape[1], 3))
            rgb_image[..., 0] = _stretch(r_data)  # reddest band -> Red
            rgb_image[..., 1] = _stretch(g_data)  # middle band  -> Green
            rgb_image[..., 2] = _stretch(b_data)  # bluest band  -> Blue
            rgb_image_8bit = (np.clip(rgb_image, 0, 1) * 255).astype(np.uint8)

            # Pink cross-hair at the centre, drawn as two opposed tick marks with
            # a small gap over the target (so it's pointed at, not covered). Made
            # more visible than before: thicker arms, a dark outline for contrast
            # against both bright and dark backgrounds, and symmetric on all sides.
            cy, cx = rgb_image_8bit.shape[0] // 2, rgb_image_8bit.shape[1] // 2
            cross_color = np.array([255, 105, 180], dtype=np.uint8)   # hot pink
            outline_color = np.array([0, 0, 0], dtype=np.uint8)       # black halo
            H, W = rgb_image_8bit.shape[:2]

            arm = 14      # length of each arm (pixels, before 2x upscale)
            gap = 5       # half-gap left clear over the target
            half = 1      # half-thickness -> pink arms are (2*half+1)=3 px wide

            def _draw_cross(thickness_half, colour):
                t = thickness_half
                # vertical arms (above and below the gap)
                y_up = slice(max(cy - gap - arm, 0), max(cy - gap, 0))
                y_dn = slice(min(cy + gap + 1, H), min(cy + gap + arm + 1, H))
                xcol = slice(max(cx - t, 0), min(cx + t + 1, W))
                rgb_image_8bit[y_up, xcol] = colour
                rgb_image_8bit[y_dn, xcol] = colour
                # horizontal arms (left and right of the gap)
                x_lf = slice(max(cx - gap - arm, 0), max(cx - gap, 0))
                x_rt = slice(min(cx + gap + 1, W), min(cx + gap + arm + 1, W))
                yrow = slice(max(cy - t, 0), min(cy + t + 1, H))
                rgb_image_8bit[yrow, x_lf] = colour
                rgb_image_8bit[yrow, x_rt] = colour

            # Draw the dark outline first (one pixel wider), then the pink on top.
            _draw_cross(half + 1, outline_color)
            _draw_cross(half, cross_color)

            img = Image.fromarray(rgb_image_8bit)
            img = img.transpose(Image.FLIP_TOP_BOTTOM)  # N up

            # Upscale for a sharper thumbnail
            upscale_factor = 2
            save_img = img.resize(
                (rgb_image_8bit.shape[1] * upscale_factor, rgb_image_8bit.shape[0] * upscale_factor),
                Image.Resampling.LANCZOS,
            )

            png_filename = img_path(name.replace(" ", "_") + ".png")
            save_img.save(png_filename, format='PNG', quality=100)
            logging.info(f"Colour composite ({survey_set}) saved as {os.path.basename(png_filename)}.")
            return img

    except Exception as err:
        logging.error(f"Colour composite image could not be created: {err}")
        # Fallback: black image with white "NA" in the centre
        width, height = 100, 100
        black_image = Image.new('RGB', (width, height), color='black')
        draw = ImageDraw.Draw(black_image)
        try:
            font = ImageFont.load_default()
            text = "NA"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            position = ((width - text_width) // 2, (height - text_height) // 2)
            draw.text(position, text, fill='white', font=font)
        except Exception as font_error:
            logging.error(f"An error occurred while drawing text: {font_error}")

        png_filename = img_path(name.replace(" ", "_") + ".png")
        black_image.save(png_filename, format='PNG', quality=100)
        return black_image


def make_combined_stamp(name, panel_size=200, title_h=26):
    """
    Tile the four stamps into a single labelled JPEG: {name}_stamps.jpeg

        [ ATLAS Target ][ ATLAS Reference ][ ATLAS Difference ][ DSS2 Catalog ]

    Any panel whose source file is missing is replaced by a black "NA" cell, so
    this never fails just because one stamp could not be downloaded.
    """
    safe = name.replace(' ', '_')
    panels = [
        (img_path(f"{safe}_ATLAS_target.jpeg"), "ATLAS Target"),
        (img_path(f"{safe}_ATLAS_ref.jpeg"),    "ATLAS Reference"),
        (img_path(f"{safe}_ATLAS_diff.jpeg"),   "ATLAS Difference"),
        (img_path(f"{safe}.png"),               "DSS2 Catalog"),
    ]

    n = len(panels)
    canvas = Image.new('RGB', (panel_size * n, panel_size + title_h), color='black')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for i, (path, title) in enumerate(panels):
        x0 = i * panel_size

        # Load the panel image, or build an "NA" placeholder.
        try:
            im = Image.open(path).convert('RGB')
            im.thumbnail((panel_size, panel_size), Image.Resampling.LANCZOS)
        except Exception:
            im = Image.new('RGB', (panel_size, panel_size), color='black')
            if font:
                ImageDraw.Draw(im).text(
                    (panel_size // 2 - 8, panel_size // 2 - 6), "NA", fill='white', font=font
                )

        # Paste the image centred within its cell, below the title strip.
        px = x0 + (panel_size - im.width) // 2
        py = title_h + (panel_size - im.height) // 2
        canvas.paste(im, (px, py))

        # Centre the title in the strip above the cell.
        if font:
            bbox = draw.textbbox((0, 0), title, font=font)
            tw = bbox[2] - bbox[0]
            draw.text((x0 + (panel_size - tw) // 2, 7), title, fill='white', font=font)

    out = img_path(f"{safe}_stamps.jpeg")
    canvas.save(out, format='JPEG', quality=95)
    logging.info(f"Combined stamp saved: {os.path.basename(out)}")
    return out


def _html_escape(s):
    """Minimal HTML escaping for text we drop into the email table."""
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def build_email_html(records):
    """
    Build the HTML email body: one responsive <table> row per target. Because the
    mail client lays out the table, columns can never misalign (unlike the old
    fixed-width text table), and the TNS/ATLAS URLs render as compact hyperlinks
    instead of long raw strings that ran together. The submitted OCS observing
    window is listed underneath each row.
    """
    # Columns shown in the table (label -> how to render each record).
    th = ('Name', 'ATLAS ID', 'RA', 'Dec', 'Disc. mag', 'Disc. date (UT)',
          'Latest mag', 'Filter', 'Latest date (UT)', 'Exposure', 'OCS id',
          'Status', 'Trigger source', 'Notes', 'Sherlock', 'Links')

    css = """
      body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d1d1f;}
      h2{margin:0 0 4px 0;}
      .sub{color:#666;margin:0 0 14px 0;font-size:13px;}
      table{border-collapse:collapse;width:100%;font-size:13px;}
      th,td{border:1px solid #ddd;padding:6px 9px;text-align:left;vertical-align:top;white-space:nowrap;}
      th{background:#f4f5f7;font-weight:600;}
      tr:nth-child(even) td{background:#fafbfc;}
      td.num{text-align:right;font-variant-numeric:tabular-nums;}
      .vis{font-size:12px;color:#333;margin:2px 0 0 0;}
      .vis code{background:#f4f5f7;padding:1px 4px;border-radius:3px;}
      a{color:#0b66c3;text-decoration:none;}
      a:hover{text-decoration:underline;}
      .foot{color:#888;font-size:11px;margin-top:16px;}
    """

    rows_html = []
    for r in records:
        links = []
        if r['crossmatch_link'] != 'NA':
            links.append(f'<a href="{_html_escape(r["crossmatch_link"])}">TNS</a>')
        if r.get('atlas_link', 'NA') != 'NA':
            links.append(f'<a href="{_html_escape(r["atlas_link"])}">ATLAS</a>')
        links_html = ' · '.join(links) if links else 'NA'

        cells = [
            f'<td>{_html_escape(r["name"])}</td>',
            f'<td class="num">{_html_escape(r["atlas_id"])}</td>',
            f'<td class="num">{r["ra"]:.5f}</td>',
            f'<td class="num">{r["dec"]:.5f}</td>',
            f'<td class="num">{r["disc_mag"]:.2f}</td>',
            f'<td>{_html_escape(r["disc_date"])}</td>',
            f'<td class="num">{r["latest_mag"]:.2f}</td>',
            f'<td>{_html_escape(r["latest_filter"])}</td>',
            f'<td>{_html_escape(r["latest_date"])}</td>',
            f'<td>{r["exp_time"]}s spec<br>+ {_html_escape(r["griz"])}</td>',
            f'<td class="num"><a href="{_html_escape(r["ocs_link"])}">{_html_escape(r["ocs_id"])}</a></td>',
            f'<td>{_html_escape(r["status"])}</td>',
            f'<td>{_html_escape(r["trigger_source"])}</td>',
            f'<td>{_html_escape(r["notes"])}</td>',
            f'<td>{_html_escape(r["sherlock"])}</td>',
            f'<td>{links_html}</td>',
        ]
        rows_html.append('<tr>' + ''.join(cells) + '</tr>')

        # Submitted OCS observing window as a sub-row spanning all columns.
        s = _html_escape(r['window_start'])
        e = _html_escape(r['window_end'])
        rows_html.append(
            f'<tr><td colspan="{len(th)}" class="vis">'
            f'<strong>OCS observing window (UTC):</strong> '
            f'<code>{s} → {e}</code> (now → next Sutherland sunrise)</td></tr>'
        )

    header_html = ''.join(f'<th>{_html_escape(h)}</th>' for h in th)
    n = len(records)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>
      <h2>🔭 ATLAS Transient OCS (Mookodi) requests</h2>
      <p class="sub"><strong>{n}</strong> new Mookodi spectroscopy request(s) submitted to the OCS.</p>
      <table><thead><tr>{header_html}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>
      <p class="foot">Combined ATLAS triplet + DSS2 finder charts are attached, one per target.</p>
    </body></html>"""


def build_email_text(records):
    """
    Plain-text fallback for text-only clients. Uses a per-target stacked block
    (label: value) rather than one very wide fixed-width row, so nothing can
    misalign and the long URLs sit on their own lines instead of colliding.
    """
    lines = ["ATLAS Transient OCS (Mookodi) requests",
             f"{len(records)} new Mookodi spectroscopy request(s) submitted to the OCS.",
             "=" * 60, ""]
    for r in records:
        links = []
        if r['crossmatch_link'] != 'NA':
            links.append(f"TNS:   {r['crossmatch_link']}")
        if r.get('atlas_link', 'NA') != 'NA':
            links.append(f"ATLAS: {r['atlas_link']}")

        lines += [
            f"{r['name']}   (ATLAS ID {r['atlas_id']})",
            "-" * 60,
            f"  RA / Dec        : {r['ra']:.5f}, {r['dec']:.5f}",
            f"  Disc. mag/date  : {r['disc_mag']:.2f}  @ {r['disc_date']} UT",
            f"  Latest mag/date : {r['latest_mag']:.2f} {r['latest_filter']}  @ {r['latest_date']} UT",
            f"  Exposure        : {r['exp_time']}s spectrum + {r['griz']} imaging",
            f"  OCS request id  : {r['ocs_id']}",
            f"  OCS request page: {r['ocs_link']}",
            f"  Status          : {r['status']}",
            f"  Trigger source  : {r['trigger_source']}",
            f"  Notes           : {r['notes']}",
            f"  Sherlock class. : {r['sherlock']}",
            f"  OCS window (UTC): {r['window_start']} -> {r['window_end']}  (now -> next sunrise)",
        ]
        for ln in links:
            lines.append(f"  {ln}")
        lines.append("")

    lines.append("Combined ATLAS triplet + DSS2 finder charts are attached, one per target.")
    return "\n".join(lines)


def query_atlas(datethreshold):

    listid = ATLAS_LIST_ID  # Bright 100Mpc Southern Transients (see ATLAS_LIST_NAMES)
    data = {'objectlistid': listid,
            'getcustomlist': True,
            'datethreshold': str(datethreshold)}

    url = ATLAS_URL + 'objectlist/'
    r = requests.post(url, data, headers=ATLAS_HEADER)
    objectListResponse = None
    if r.status_code == 200:
        objectListResponse = r.json()
        print(json.dumps(objectListResponse, indent=2))
    else:
        print('Oops, status code is', r.status_code)
        print(r.text)

    if objectListResponse is None:
        print("Bad response from the objectlist API")
        exit(1)

    return objectListResponse


def main(fresh_hours=24):

    # Only act on FRESH targets: those DISCOVERED within the last FRESH_HOURS.
    # The ATLAS query looks back a bit further than this (so boundary objects
    # aren't missed to processing lag) and we then filter precisely on the
    # discovery time (earliest_mjd) below. Overridable via --fresh-hours for
    # testing (default 24 h).
    FRESH_HOURS = fresh_hours
    window = 2 * FRESH_HOURS  # hours to look back in the ATLAS query
    logging.info(f"freshness window: {FRESH_HOURS} h (ATLAS look-back {window} h)")

    # Persistent dedup file (NOT per-day). Because this runs every 30 min and a
    # target stays "fresh" for 24h, a per-day file would re-trigger an object
    # discovered just before midnight. A single file avoids that. (It grows
    # slowly; prune it occasionally if you like.)
    submitted_requests = os.getcwd() + "/submitted_requests.csv"
    if not os.path.exists(submitted_requests):
        logging.info("Submitted request file does not exist, creating with header and dummy info")
        f = open(submitted_requests, "w")
        # Dedup is keyed on the 19-digit ATLAS ID (stable), not the name (which
        # can change when an object gets/updates its ATLAS designation).
        f.write('\"Submitted ATLAS ID\",\"Submitted Target\",\"Submitted Date\"\n')  # header
        f.write('0,dummy,' + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '\n')  # dummy so file is not empty
        f.close()
    else:
        logging.info("Submitted request file already exists")

    ### Query ATLAS for objects
    logging.info('Querying ATLAS with a date threshold of: {}'.format(Time.now() - TimeDelta(window / 24, format='jd')))
    object_list = query_atlas(Time.now() - TimeDelta(window / 24, format='jd'))
    logging.info('Query done.')

    try:
        submitted_requests_data = ascii.read(submitted_requests)
    except Exception as err:
        logging.error('Could not open submitted requests csv file')
        logging.error((Exception, err))

    if object_list == []:
        logging.error('No objects in ATLAS list')
        return

    print(json.dumps(object_list, indent=2))

    included_targets = []     # names actually included (fresh + bright + new)
    slack_records = []        # structured per-target data; also drives the email bodies

    # Set of already-submitted 19-digit ATLAS IDs (as strings) for dedup. The ID
    # is stable even if an object later gets/updates its ATLAS designation, so we
    # dedup on it rather than on the (mutable) name.
    try:
        done_ids = {str(v).strip() for v in submitted_requests_data["Submitted ATLAS ID"]}
    except (KeyError, TypeError):
        # Older file without the ID column: no IDs to match against.
        done_ids = set()

    for target in object_list:
        # Stable 19-digit ATLAS ID (the numeric object id, NOT the designation).
        atlas_id = str(target.get("id", "")).strip()

        # Some objects have a null atlas_designation; fall back to the TNS name
        # or the numeric id so downstream formatting/filenames never see None.
        name = (target.get("atlas_designation")
                or target.get("other_designation")
                or f"id{target.get('id', 'unknown')}")

        if atlas_id and atlas_id in done_ids:
            logging.info(f"Already submitted a request for ATLAS ID {atlas_id} ({name}), skipping")
            continue

        # Freshness gate: skip unless DISCOVERY was < FRESH_HOURS ago.
        # (earliest_mjd = discovery; latest_mjd would be the most recent detection.)
        age_hours = (Time.now().mjd - float(target["earliest_mjd"])) * 24.0
        if age_hours > FRESH_HOURS:
            logging.info(
                f"{name} discovered {age_hours:.1f} h ago "
                f"(> {FRESH_HOURS} h), not fresh - skipping"
            )
            continue

        # Brightness gate: only trigger on targets at least as bright as
        # MAG_LIMIT (latest ATLAS mag). Skip if fainter, or if the mag is
        # missing/NaN (can't scale the exposure, so don't guess).
        latest_mag = target.get("latest_mag")
        try:
            latest_mag = float(latest_mag)
        except (TypeError, ValueError):
            logging.info(f"{name} has no usable latest_mag ({latest_mag!r}) - skipping")
            continue
        if not np.isfinite(latest_mag) or latest_mag > MAG_LIMIT:
            logging.info(
                f"{name} latest mag {latest_mag} fainter than limit {MAG_LIMIT} - skipping"
            )
            continue

        try:
            target_coords = SkyCoord(target["ra_avg"], target["dec_avg"], unit=(u.deg, u.deg))

            # Observing window: now -> next Sutherland sunrise. The OCS scheduler
            # is responsible for rejecting anything not actually observable.
            window_start = Time.now()
            window_end = next_sutherland_sunrise(window_start)
            exp_time = mookodi_exposure_time(latest_mag)

            # Submit the Mookodi spectroscopy request via aeonlib. Raises on
            # validation/submission failure -> caught below, target skipped.
            submitted = send_observing_request_to_OCS(
                name, latest_mag,
                target["ra_avg"], target["dec_avg"],
                window_start, window_end,
            )

            with open(submitted_requests, "a") as f:
                f.write(f"{atlas_id},{name},{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

            # Dates without fractional seconds
            disc_date = Time(target["earliest_mjd"], format='mjd').datetime.strftime("%Y-%m-%d %H:%M:%S")
            latest_date = Time(target["latest_mjd"], format='mjd').datetime.strftime("%Y-%m-%d %H:%M:%S")

            # Crossmatch link
            crossmatch_value = target['external_crossmatches'] or 'NA'
            crossmatch_link = f"https://www.wis-tns.org/object/{crossmatch_value}" if crossmatch_value != 'NA' else 'NA'

            # ATLAS Transient Server candidate page (uses the 19-digit id).
            atlas_link = f"{ATLAS_CANDIDATE_URL}{atlas_id}/" if atlas_id else 'NA'

            included_targets.append(name)

            # Structured copy of the same fields for the email/Slack alerts.
            # For OCS the meaningful scheduling info is the exposure time and the
            # submitted observing window (the OCS handles visibility itself).
            slack_records.append({
                "name": name,
                "atlas_id": atlas_id,
                "status": TRIGGER_STATUS,
                "trigger_source": TRIGGER_SOURCE,
                "notes": TRIGGER_NOTES,
                "atlas_link": atlas_link,
                "ra": target['ra_avg'],
                "dec": target['dec_avg'],
                "disc_mag": target['earliest_mag'],
                "disc_date": disc_date,
                "latest_mag": latest_mag,
                "latest_filter": target['latest_filter'] or 'NA',
                "latest_date": latest_date,
                "exp_time": exp_time,
                "griz": f"{len(GRIZ_IMAGING_FILTERS)}×{GRIZ_IMAGING_EXPTIME}s "
                        f"{''.join(f[0] for f in GRIZ_IMAGING_FILTERS)}",
                "ocs_id": submitted.id,
                "ocs_link": f"{OCS_REQUESTGROUP_URL}{submitted.id}",
                "window_start": window_start.iso[:16],
                "window_end": window_end.iso[:16],
                "crossmatch_link": crossmatch_link,
                "sherlock": target['sherlockClassification'],
            })

            # DSS2 finder chart
            try:
                download_stamp(target_coords, name)
            except Exception as err:
                logging.error("DSS2 finder stamp could not be created")
                logging.error((Exception, err))

            # ATLAS triplet postage stamps (target/ref/diff).
            # NOTE: the stamp/objects API needs the numeric 19-digit id, which
            # is target['id'] in the objectlist response (NOT the designation).
            try:
                download_atlas_stamps(atlas_id, name, target=target)
            except Exception as err:
                logging.error("ATLAS triplet stamps could not be downloaded")
                logging.error((Exception, err))

            # Combine the triplet + DSS2 finder into one labelled jpeg
            try:
                make_combined_stamp(name)
            except Exception as err:
                logging.error("Combined stamp could not be created")
                logging.error((Exception, err))

            logging.info(f"Submitted a request for {name}")
        except Exception as err:
            logging.error(f"Could not submit OCS Mookodi request for {name}")
            logging.error((Exception, err))
            continue

    if not included_targets:
        logging.info('no new submissions, not sending email')
    else:
        email_text = build_email_text(slack_records)
        email_html = build_email_html(slack_records)
        send_email(
            email_text,
            email_addresses,
            'ATLAS Transient OCS (Mookodi) requests',
            included_targets,
            html_message=email_html,
        )
        # Post the same alert to Slack in parallel. Independent of the email:
        # a failure in either path is logged but doesn't block the other.
        send_slack(slack_records, included_targets)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ATLAS -> OCS (Mookodi) transient listener/trigger."
    )
    parser.add_argument(
        "--fresh-hours",
        type=float,
        default=24,
        metavar="H",
        help="Only trigger on targets discovered within the last H hours "
             "(default: 24). Handy for testing - e.g. widen to reprocess older "
             "targets, or narrow to only the very newest.",
    )
    args = parser.parse_args()
    main(fresh_hours=args.fresh_hours)
