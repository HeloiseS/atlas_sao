#!/usr/bin/env python3
# 
# TNS classification helper - Init (2026-08-25)
# Authors: Claude (Bulk of Code) + Heloise (Review and Comments and Refactors)
# Note: This is one big file instead of being split up so it's easy for a colleague to copy paste on their machine
# 
# HOW TO USE: 
# >>> python tns_upload_classification.py
# 
# NOTE: The path to the spectrum file CANNOT handle wild cards like ~. You need to give the actual path

import argparse
import json
import os
import time
from collections import OrderedDict
from datetime import datetime
import logging
import requests
import os
import yaml


### CONSTANTS

EXT_HTTP_ERRORS = [403, 500, 503]
ERR_MSG = ["Forbidden", "Internal Server Error: Something is broken", "Service Unavailable"]
SLEEP_SEC = 5
TIMEOUT = 30


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), 'tns_config_MINE.yaml'
)

### LOGGING SET UP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

### HELPER FUNCTIONS

def load_tns_config(config_path: str | None = None, bot_name: str = "lvra") -> dict:
    if config_path is None:
        config_path = os.environ.get(f'{bot_name}_CONFIG_TNS', DEFAULT_CONFIG_PATH)

    with open(config_path) as f:
        return yaml.safe_load(f)

def _tns_marker(bot_id, bot_name):
    "Create correctly formatter TNS marker for our bot"
    return 'tns_marker{"tns_id": "' + str(bot_id) + '", "type": "bot", "name": "' + bot_name + '"}'


def _log_status(response):
    """Prettified logging of the status (Logging goes to stdout)"""
    try:
        payload = response.json()
        logging.info(f"Status code: [ {payload['id_code']} - '{payload['id_message']}' ]")
    except (ValueError, KeyError):
        status = response.status_code
        if status == 200:
            msg = "OK"
            logging.info(f"Status code: [ {status} - '{msg}' ]")
        elif status in EXT_HTTP_ERRORS:
            msg = ERR_MSG[EXT_HTTP_ERRORS.index(status)]
        else:
            msg = "Undocumented error"
        logging.error(f"Status code: [ {status} - '{msg}' ]")


def upload_files(api_url, headers, api_key, file_paths):
    """Upload the spectra to TNS"""
    files_data = {}
    
    for i, path in enumerate(file_paths):
        name = os.path.basename(path)
        # At present (2026-08-25) we only get .txt from Slack bots
        # but keeping other cases just in case
        if name.lower().endswith(('.asci', '.ascii', '.txt', '.dat')):
            value = (name, open(path), 'text/plain')
            logging.info(f"Found TEXT file for upload: {name}")
        else:

            value = (name, open(path, 'rb'), 'application/fits')
            logging.info(f"Found FITS file for upload: {name}")

        files_data[f'files[{i}]'] = value

    response = requests.post(
        f'{api_url}/set/file-upload',
        headers=headers,
        data={'api_key': api_key},
        files=files_data,
    )


    return response


def send_report(api_url, headers, api_key, report_path):
    """Send the report (here likely will be classification report)"""
    with open(report_path) as f:
        parsed = json.load(f, object_pairs_hook=OrderedDict)

    response = requests.post(
        f'{api_url}/set/bulk-report',
        headers=headers,
        data={'api_key': api_key, 'data': json.dumps(parsed)},
    )

    return response


def get_reply(api_url, headers, api_key, report_id):
    """Get the TNS reply to check our report went in"""

    # We need to sleep otherwise we get a 404 - becasue the TNS back end has to catch up 
    time.sleep(SLEEP_SEC)
    elapsed = SLEEP_SEC

    # Now we can ask TNS about our REPORT ID
    response = requests.post(
        f'{api_url}/get/bulk-report-reply',
        headers=headers,
        data={'api_key': api_key, 'report_id': report_id},
    )

    # Nice trick by claude - if we still get a 404 we'll try again until we've
    # ran out of patience (Time out set as a constant at the top of the file)
    while response.status_code == 404 and elapsed <= TIMEOUT:
        time.sleep(SLEEP_SEC)
        elapsed += SLEEP_SEC
        response = requests.post(
            f'{api_url}/get/bulk-report-reply',
            headers=headers,
            data={'api_key': api_key, 'report_id': report_id},
        )
    return response


def _load_json(path):
    "Returns opened JSON data"
    with open(path) as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def _prompt(question, default=None):
    "Helper for the dialogue prompts"
    suffix = f" [{default}]" if default is not None else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer if answer else default


def run_dialogue():
    """Interactive dialogue to fill the TNS classification report
    
    Returns
    --------
    report: filled-in template dict
    spectrum_files: OrderedDict of local file paths still to be uploaded (ascii_file/fits_file/
    related_file are None if not given; ascii_file is mandatory).

    Notes:
    ------
    # DIALOGUE LOGIC (Defaults should be flagged in square brackets)
    # >>> Telescope/Instrument [Mookodi]/SALT:
    # (if Mookodi or None: instrumentid=279 (don't change default in template), if SALT instrumentid= 117 )
    # >>> Spectral Type:
    # (regex the type given in list of objtypes, then use the pairs of [type_id: type_string] in next dialogue)
    # >>> Type ID PAIR_1 / PAIR_2 / etc..:
    # (set objtypeid)
    # >>> Obs. Date [Default = TODAY_DATE]:
    # (set obsdate)
    # >>> Redshift:
    # (set redshift)
    # >>> Exposure time:
    # (set exp.time)
    # >>> Reducer [S. de Wet]:
    # (set reducer)
    # >>> Additional Remarks [None]:
    # (To Go in Top level remarks)
    """

    # ############## #
    # 0. SET UP 
    # ############## #

    aux_path = os.path.join(os.path.dirname(__file__), 'tns_codes.json')
    template_path = os.path.join(os.path.dirname(__file__), 'tns_classification_report_template.json')

    objtypes = _load_json(aux_path)['data']['objtypes']
    report = _load_json(template_path)
    entry = report['classification_report']['0']

    # ############### #
    # 1. OBJ NAME 
    # ############### #
    name = ''
    while not name:
        name = input("Object name: ").strip()
    entry['name'] = name

    # ############### #
    # 2. TELESCOPE 
    # ############### #
    # Sets the instrumentid and the default remark.

    telescope = _prompt("Telescope/Instrument Mookodi/SALT", "Mookodi")
    recognised = False
    while recognised is False:
        if telescope.lower() == 'salt':
            instrumentid = "117"
            default_remark = (
                "The classification target was automatically flagged for follow-up by the "
                "Virtual Research Assistant (Stevance et al. 2025), while observations with "
                "SALT were manually scheduled."
            )
            recognised = True
        elif telescope is None or telescope.lower() == 'mookodi' or telescope.lower() == 'lesedi':
            instrumentid = "279"
            default_remark = (
                "The classification target was automatically sent for follow-up by the "
                "Virtual Research Assistant (Stevance et al. 2025). Observations were "
                "programatically triggered using the ATLAS API Client (Stevance et al. 2026) "
                "and the SAAO Intelligent Observatory framework (Erasmus et al. 2024, Erasmus "
                "et al. 2025)"
            )
            recognised = True
        else:
            logging.error(f'Telescope {telescope} not recognised')

    entry['spectra']['0']['instrumentid'] = instrumentid

    # Claude wrote this for the TNS classification dialogue (2026-08-25):
    # spectypeid isn't flagged mandatory in the TNS manual, but the live sandbox
    # rejects a blank value once a spectrum is submitted. "1" = Object (the
    # transient itself, vs. Host/Sky/Synthetic) - the only sensible value here.
    entry['spectra']['0']['spectypeid'] = "1"

    # ############### #
    # 3. SPEC. TYPE
    # ############### #
    objtypeid = None
    while objtypeid is None:
        search = input("Spectral Type (search term, e.g. 'SN Ia'): ").strip()
        matches = {tid: tname for tid, tname in objtypes.items()
                   if search.lower() in tname.lower()}
        if not matches:
            print("No matching object types, try again.")
            continue

        for tid, tname in sorted(matches.items(), key=lambda kv: int(kv[0])):
            print(f"  {tid}: {tname}")

        choice = input("Enter the objtypeid from the list above: ").strip()

        if choice in matches:
            objtypeid = choice
        else:
            print("That id wasn't in the list above, try again.")

    entry['objtypeid'] = objtypeid

    # ############### #
    # 4. OBS DATE
    # ############### #
    today = datetime.now().strftime('%Y-%m-%d')
    obsdate = None
    while obsdate is None:
        candidate = _prompt("Obs. Date (UT), format YYYY-MM-DD or YYYY-MM-DD HH:MM:SS", today)
        candidate = candidate.strip().strip('\'"')
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                datetime.strptime(candidate, fmt)
                obsdate = candidate
                break
            except ValueError:
                continue
        if obsdate is None:
            print("Could not parse date. Expected format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (UT). Try again.")
    entry['spectra']['0']['obsdate'] = obsdate

    # ############### #
    # 5. REDSHIFT
    # ############### #
    entry['redshift'] = _prompt("Redshift", "") or ""

    # ############### #
    # 6. EXP. TIME
    # ############### #
    entry['spectra']['0']['exptime'] = _prompt("Exposure time (s)", "") or ""

    # ############### #
    # 7. REDUCER
    # ############### #
    entry['spectra']['0']['reducer'] = _prompt("Reducer", "S. de Wet")

    # ############### #
    # +. OBSERVERS ADDED
    # ############### #
    entry['spectra']['0']['observer'] = _prompt("Observer", "N. Erasmus, S. Potter, C. van Gend, H. Worters, P. Rabe (all SAAO)") or ""

    # ############### #
    # 8. REMARKS
    # ############### #
    entry['spectra']['0']['remarks'] = default_remark

    extra_remarks = _prompt("Additional Remarks", "None")
    entry['remarks'] = extra_remarks if extra_remarks and extra_remarks != "None" else ""

    # ############### #
    # 9. FILES
    # ############### #
    ascii_file = None
    while not ascii_file:
        candidate = input("Path to ASCII spectrum file: ").strip()
        if os.path.isfile(candidate):
            ascii_file = candidate
        else:
            print("File not found. DO NOTUSE WILD CARDS (e.g. ~ or *). Try again.")

    fits_file = input("Path to FITS spectrum file (optional, Enter to skip): ").strip() or None
    if fits_file and not os.path.isfile(fits_file):
        print("FITS file not found, skipping.")
        fits_file = None

    
    related_file = input("Path to a related plot/image file (optional, Enter to skip): ").strip() or None
    related_comment = ""
    if related_file and not os.path.isfile(related_file):
        print("Related file not found, skipping.")
        related_file = None
    elif related_file:
        related_comment = input("Comment for related file (optional): ").strip()

    
    spectrum_files = OrderedDict([
        ('ascii_file', ascii_file),
        ('fits_file', fits_file),
        ('related_file', related_file),
        ('related_file_comment', related_comment),
    ])

    return report, spectrum_files


def main():
    """Full Script"""

    # ########################## #
    # 0. PARSING USER ARGUMENTS
    # ########################## #

    # Literaly parsing CLI arguments
    parser = argparse.ArgumentParser(description="Upload a TNS classification (bulk) report.")
    parser.add_argument('--config', default=None, help='Explicit path to the TNS config yaml (overrides env/default).')

    args = parser.parse_args()

    # Prompting the user for details
    report, spectrum_files = run_dialogue()
    entry = report['classification_report']['0']

    # ############################### #
    # 1. SET UP FROM CONFIG AND ARGS
    # ############################### #

    # TODO: LATER - change bot from LVRA to what we'll want to use  [TBD]
    bot_name = 'lvra'

    if args.config:
        logging.info(f"Looking for Config File at: {args.config}")
    else:
        logging.info(f"Default Config File location: {DEFAULT_CONFIG_PATH}")

    config = load_tns_config(config_path=args.config, bot_name=bot_name)
    api_url = f"https://{config['tns_host']}/api"
    headers = {'User-Agent': _tns_marker(config['tns_bot_id'], config['tns_bot_name'])}
    api_key = config['tns_api_key']

    # ############################### #
    # 2. SENDING THE SPECTRA FILES
    # ############################### #

    files_to_upload = [p for p in (
        spectrum_files['ascii_file'],
        spectrum_files['fits_file'],
        spectrum_files['related_file'],
    ) if p]

    logging.info(f"Uploading {len(files_to_upload)} file(s) to {config['tns_host']}...")
    response = upload_files(api_url, headers, api_key, files_to_upload)

    # Prints the right log depending on response
    _log_status(response)

    if response.status_code != 200:
        logging.error("File upload failed, aborting without sending a report.")
        return
    uploaded_names = response.json()['data']
    logging.info(f"Uploaded: {uploaded_names}")

    # Map the TNS-assigned filenames back onto the report, in upload order.
    uploaded = iter(uploaded_names)
    entry['spectra']['0']['ascii_file'] = next(uploaded)
    if spectrum_files['fits_file']:
        entry['spectra']['0']['fits_file'] = next(uploaded)
    if spectrum_files['related_file']:
        entry['related_files']['0']['related_file_name'] = next(uploaded)
        entry['related_files']['0']['related_file_comments'] = spectrum_files['related_file_comment']

    # ############################### #
    # 3. SENDING THE REPORT
    # ############################### #

    # 3.1 Write the completed report to disk, then send it
    reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    safe_name = entry['name'].replace(' ', '_')
    timestamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    report_path = os.path.join(reports_dir, f"{safe_name}_{timestamp}_classification_report.json")
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    logging.info(f"Report written to {report_path}")

    logging.info(f"Sending report '{report_path}'...")
    response = send_report(api_url, headers, api_key, report_path)

    _log_status(response)

    # 3.2 If not successful, log and exit
    if response.status_code != 200:
        logging.error("Report was not sent.")
        return

    # 3.3 If success, grab the report ID so we can poll TNS 
    report_id = response.json()['data']['report_id']

    logging.info(f"Polling for reply on report ID = {report_id}...")
    response = get_reply(api_url, headers, api_key, report_id)
    _log_status(response)

    try:
        feedback = response.json()['data']['feedback']
        logging.info(json.dumps(feedback, indent=2))
    except (ValueError, KeyError):
        logging.info("feedback: {}")


if __name__ == '__main__':
    main()
