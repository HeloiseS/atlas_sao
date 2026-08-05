#!/bin/bash

# SLACK BOT
# --------------------
#
# Wrapper script that sets the environment and the python path
# then calls the python script (in the atlas_sao package).

LOCKFILE="$(dirname "$0")/.locks/slackbot.lock"
mkdir -p "$(dirname "$LOCKFILE")"
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Previous run still in progress, skipping."; exit 1; }

export PYTHONPATH=/home/atlas/code/atlasapiclient
export PYTHONPATH="${PYTHONPATH}:/home/atlas/code/atlas_sao"
export el0iz_CONFIG_SLACK=/home/atlas/code/atlas_sao/atlas_sao/config_files/slack_config_MINE.yaml

echo "Polling #atlas_sao_bot for new messages."
t_start=$(date +%s)
/home/atlas/anaconda3/envs/vra/bin/python /home/atlas/code/atlas_sao/atlas_sao/slackbot.py
t_end=$(date +%s)

echo "Finished polling Slack."
delta_t=$((t_end - t_start))

echo "Slack bot took $delta_t seconds."
