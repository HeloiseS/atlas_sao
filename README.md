# ATLAS SAO pipelines

Last Updated: 2026-08-05

# User References

There are currently 3 lists of interest:
- **Bright 100Mpc Southern Transients (Custom List 16)** | **Mookodi** : Young Transients within 100 Mpc that have not yet been classified, with VRA Score > 8.5, brighter than 17 mag
- **100Mpc Southern Transients (Custom List 2)** | **SALT**: Young Transients that have not yet been classified, with VRA Score > 8.5, within 100 Mpc. No mag limit. _FED DIRECTLY FROM PSAT-SERVER INGEST SCRIPT_
- **Southern Transients at Peak (Custom List 17)** | **Mookodi**: Transients "at peak". Current definition of "at peak" is: the last 3 lc points are all real detections brighter than 16.9 mag (allowing for their 1-sigma error bar). 

---

# Dev References

## Slack Bot

The slack bot that reads the #atlas_sao_bot messages uses the `el01z` credentials. It has been running in prod on db1 for a few days now (polling into `slack_messages`).

**To-Do**
- [ ] Simon to confirm he can follow the human message format below for SALT/Mookodi triggers/observations
- [x] Build the parser for human messages (Simon's SALT/Mookodi trigger/observed messages)

### Message format specs

These are the "must-haves" atlas_sao's Slack ingestion (`atlas_sao/slackbot.py`) depends on. If either Nic's bot or a human sender's message stops matching these, parsing breaks - usually silently (a field just comes back `None`/unmatched, not a hard error). Anyone changing message formats on their end should check against this list first, and this file should be kept in sync with the parser whenever the format changes.

#### Bot messages (Nic's Mookodi bot)

**Status report messages** (Triggered / Observed), one ATLAS object per message:
- Top-level message `text` must mention the telescope name ("SALT" or "Mookodi", case-insensitive, anywhere in the text) - this is how we tag which telescope a message is about.
- Must contain a Block Kit `section` block whose own heading `text` starts with the ATLAS **name** in bold, e.g. `*ATLAS26jij*` or `*ATLAS26jij (exposure 2/2)*` for multi-exposure reports.
- That section's `fields` list must use the `*Label*\n<value>` pattern (bold label, newline, value) for each of the following. All are required unless marked optional:
    - `*ATLAS ID*` - the numeric ATLAS ID. **Required on every message that has one available** - do not rely on ATLAS name alone, we need to be able to identify the object without looking anything up elsewhere.
    - `*Status*` - e.g. `Triggered`, `Observed`
    - `*RA / Dec*` - format `<ra>, <dec>` in decimal degrees, comma-separated
    - `*Latest*` - format `<mag> <filter> · <date> UT`, e.g. `16.72 o · 2026-08-05 17:55:32 UT` - we only parse the leading number
    - `*Trigger source*` - free text, the custom list name that triggered this
    - `*Notes*` - free text, or the **literal string `None`** (not `N/A`, `-`, or blank) when there's nothing to say. We normalize exactly that string to a real empty value - anything else gets stored as literal text.

**Spectrum CSV messages** (file-share, one per exposure):
- Sent as a Slack file share with exactly one CSV file per message. If more than one CSV is ever attached to a single message, only the first is used (we log a warning, the rest are silently dropped) - so please keep it to one CSV per message.
- The file's `filetype` must be `csv`.
- The message's top-level `text` (not the file's `title`) must contain `ATLAS ID <id>` - this is what we parse to identify the object. Without it, the CSV is not downloaded and the message is logged with `atlas_id` NULL, on purpose (a missing ID here should be a loud, visible problem, not silently guessed at). e.g. `*ATLAS26jij*  ·  ATLAS ID 1135314261002652300  ·  Observed — quicklook products`.
- If the text also has a bold `*<name>*` lead-in that's a real ATLAS name (not just `id<ATLAS ID>` echoed back), we store it too - but it's informational only, never required.
- The file's `name` is saved as-is as the local filename - no format requirement on our end, but please keep it unique per exposure (current convention `<ATLAS name or id>_<exposure>_<frame id>.csv` works fine).
- Companion PNG files (acquisition / spectrum image / spectrum plot) are currently ignored - not stored anywhere.

#### Human messages (Simon, SALT and Mookodi)

For a message to be recognised as a real report (and not casual chat in the bot channel that happens to mention a keyword like "trigger"), it must contain, anywhere in the text (case-insensitive):
- A line that is just `REPORT` on its own - this is the tag that says "this is a real report, not chat". No message gets parsed without it. `REPORT` is meant as the general tag for any kind of human report, not just SALT triggers.
- One status keyword (see below), to say what's happening
- One telescope keyword (see below), to say which telescope this is about
- A line `ATLAS ID: <atlas id>` with the numeric ATLAS ID, **exactly 19 digits** - **always the ID, not just the name** (see above for why this matters). A missing or wrong-length ID does not get silently guessed at - it's logged as an error and the message is dropped.

Status keywords - the message just needs to contain the word (case-insensitive), not an exact phrase:
- `trigger` - a target has been submitted/triggered
- `observed` - a target has actually been observed
- `fail` - the trigger/observation failed

Telescope keywords - same, just the word anywhere in the text:
- `salt` - SALT
- `mookodi` or `lesedi` - Mookodi (Lesedi is the telescope hosting the Mookodi instrument, used as a synonym)

Example:
```
REPORT
SALT TRIGGER
ATLAS ID: 1135314261002652300
```
```
REPORT
SALT OBSERVED
ATLAS ID: 1135314261002652300
Notes: seeing was poor, may need a re-do
```
```
REPORT
MOOKODI TRIGGER FAILED
ATLAS ID: 1135314261002652300
```
The `Notes:` line is optional free text and can be omitted entirely. Everything else in the message (extra chat, @-mentions, etc.) is ignored - we only look for the `REPORT` tag, the status/telescope keywords, and the ATLAS ID line.


## Bright 100Mpc Southern Transients
Custom List: 16

**Constraints**
- Mag Threshold: 17 mag
- Not yet classified
- VRA Score>8.5 (from input)
- <100Mpc (from input)

**Inputs**
- Mookodi Stageing list (populated by Ken's ingest script - Fast Track and VRA Score>8.5)

**Script**: `mookodiListWizard.py` 
- **Clean Live List**: Removes objects that no longer pass our constraints from the Live list
- **Logs removal from Live list** in `bk_young_fast_track` by adding timestamp of when a given atlas\_id was removed from custom list 16.
- **Clean Staging List**: Removes objects that no longer pass our constraints from the Staging list (custom list  = 2). _This is not logged in a table_ (it would be duplicate of loggin above)
- **Adds alerts to the Live list** 
- **Logs adds** in  `bk_young_fast_track` by adding timestamp and the **vra score** at time of adding. 

### `bk_young_fast_track`

```
id  atlas_id             date_added           date_removed  vra_score_when_added  version  timestamp          
--  -------------------  -------------------  ------------  --------------------  -------  -------------------
1   1115743850202903700  2026-07-07 10:21:09                9.17244                        2026-07-07 10:21:09
```


### Why is there a staging list and a live list?
Because the staging list used to be where Mookodi would get its feed from but it would very often take spectra of objects that are too faint. The Live lists is only filled with objects that reach a certain magnitude threshold (and are yet unclassified).


## Southern Transients at Peak

Custom List: 17


**Constraints**
- Already classified as good
- Mag Threshold (will need better "at peak" descriptor)

For now we will use a dumb placeholder: **brighter than 16.9 mag**. Why? because for mookodi we usually target things within 100 Mpc. that's distance modulus 35, so absolute mag 19. That's the peak of a Ia SN at 100Mpc. So we won't be filling up the list with things that are too distant. Also 16.9th and brighter is a really good SNR for mookodi, so we'll only be targetting bright things, nearby, most likely near peak. And those that are so nearby that they are not near peak will be much less numerous because the volume is much smaller. So this is a great place to start using the list, then I'll see what targets end up "contaminating" the list and I'll refine later.

**2026-07-20 update**: 16 mag was too restrictive (missed genuine near-peak objects between 16 and 16.9), and checking only the single latest lc point wasn't restrictive enough — a single bogus bright detection could get an object onto the list. Fixed both: threshold moved to 16.9 mag, and now we require the **last 3** lc points to each be real detections (not non-detections) that are brighter than 16.9 allowing for their 1-sigma error bar (`mag - magerr < 16.9`). If the last 3 points are non-detections, or any of them fails that check, the object is removed from the list (or never added in the first place). See `is_at_peak()` in `mookodiPeakListWizard.py`.

**2026-07-21 update ([#27](https://github.com/HeloiseS/atlas_sao/issues/27))**: the "last 3 points" check above only looked at `lc`, but non-detections don't show up there — they live in a separate `lcnondets` field (limiting mag only, no mag/magerr). So an object with old bright `lc` points and thousands of recent non-detections in `lcnondets` was staying on the list forever, since those non-detections were invisible to the check. Fixed by merging `lc` and `lcnondets` on mjd before taking the last 3 points, so a recent non-detection now correctly counts as one of the most recent visits.


**Inputs**
- Objects that have been classified as good in the last X weeks (i.e are set as Active in `xtgal_watchlist` table.)

**Script**: `refreshXtgal.py`
- Finds all atlas\_ids in VRA Scores table (`tsc_vra_scores`) which have been labeled as extragalacitc by a person (`preal == 1.0`, `pgal==0.0`).
- Puts them in the `xtgal_watchlist` table with Active = 1. 
- Find alerts that are more than X weeks old and sets Active = 0 


**Script**: `mookodiPeakListWizard.py` 
- **Clean Salt List**: Removes objects that no longer pass our constraints from the Live list
- **Logs removal from Salt list** in `bk_peak` by adding timestamp of when a given atlas\_id was removed from custom list 14.
- **Adds alerts to the Salt list** 
- **Logs adds** in  `bk_peak` by adding timestamp and the **vra score** at time of adding. 


### `bk_peak`

```
id  atlas_id             date_added           date_removed  vra_score_when_added  version  timestamp          
--  -------------------  -------------------  ------------  --------------------  -------  -------------------
25  1200738260210707300  2026-07-01 15:17:23                                               2026-07-01 15:17:23
```

### `xtgal_watchlist`

```
id    atlas_id             active  date_added           last_mag  last_mag_err  last_mag_filt  timestamp          
----  -------------------  ------  -------------------  --------  ------------  -------------  -------------------
4440  1132830610110316600  1       2026-07-08 08:47:55                                         2026-07-08 08:47:55

```

`last_mag`/`last_mag_err`/`last_mag_filt` are deliberately left unpopulated ([#20](https://github.com/HeloiseS/atlas_sao/issues/20)) — not needed for the current pipeline, kept in the schema in case a future use case needs them.



# Heloise's Quick Notes

To find the number of objects (unique) added to a list on each day you can do:

```sql
select substr(date_added, 1, 10) as day_added, count(distinct(atlas_id)) from bk_peak group by day_added;
```

## SALT List [RETIRED -: 202-07-30]

Custom List: 14

**Constraints**
- Not yet classified
- VRA Score>9.0
- NOT `ORPHANS`

**Inputs**
- Eyeball list. (Not Fast Track. If user wants fast track they can also use the Mookodi Young Trasnients Live List)


**Script**: `saltListWizard.py` 
- **Clean Salt List**: Removes objects that no longer pass our constraints from the Live list
- **Logs removal from Salt list** in `bk_young_not_fast_track` by adding timestamp of when a given atlas\_id was removed from custom list 14.
- **Adds alerts to the Salt list** 
- **Logs adds** in  `bk_young_not_fast_track` by adding timestamp and the **vra score** at time of adding. 


### `bk_young_not_fast_track`
```
id  atlas_id             date_added           date_removed  vra_score_when_added  version  timestamp          
--  -------------------  -------------------  ------------  --------------------  -------  -------------------
8   1141048460225429100  2026-07-06 21:29:23                9.77169                        2026-07-06 21:29:23
```
