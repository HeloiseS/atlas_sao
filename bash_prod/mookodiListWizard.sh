#!/bin/bash

# MOOKODI LIST WIZARD
# --------------------
#
# Wrapper script that sets the environment and the python path
# then calls the python script (in the atlas_sao package). 
# Also times the script [in the wrong way? - I could just use
# the time command no?].
#
#

LOCKFILE="$(dirname "$0")/.locks/mookodiListWizard.lock"
mkdir -p "$(dirname "$LOCKFILE")"
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Previous run still in progress, skipping."; exit 1; }

export PYTHONPATH=/home/atlas/code/atlasapiclient
export PYTHONPATH="${PYTHONPATH}:/home/atlas/code/atlas_sao"
export CONFIG_ATLASAPI=/home/atlas/code/atlasapiclient/atlasapiclient/config_files/api_config_MINE.yaml

echo "Cleanup and populate Mookodi lists."
t_start=$(date +%s)
/home/atlas/anaconda3/envs/vra/bin/python /home/atlas/code/atlas_sao/atlas_sao/mookodiListWizard.py
t_end=$(date +%s)

echo "Finished with Mookodi lists."
delta_t=$((t_end - t_start))

echo "Mookodi update took $delta_t seconds."
