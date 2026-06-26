# CLAUDE.md - Project Level Instructions - ATLAS SAO Follow-up

## About the project

The South African Observatory has a two telescopes that can be used for follow-up observations of transients found by the ATLAS sky survey: 
- The Lesedi telescope (with the Mookodi instrument, which is how I refer to it most of the time)
- The SALT telescope. 

Currently I have codes to send transient candidates for follow-up to Mookodi as soon as they are bright enough, but they are usually borderline and we never go back when the transients are near peak (at their brightest). We also do not yet have a connection to SALT.

Goals (reordered 2026-06-17 — refactor before adding new analysis logic):
0. [DONE] fix two bugs upstream in `atlasapiclient` ([issue #42](https://github.com/HeloiseS/atlasapiclient/issues/42), [issue #43](https://github.com/HeloiseS/atlasapiclient/issues/43)) that break chunked/batched writes — merged in [PR #44](https://github.com/HeloiseS/atlasapiclient/pull/44). Reliable batch writes are now in place for goals 1 and 2 below.
1. Refactor the current Mookodi workflow for young transients (`mookodiListWizard.py`) — clean up the code we already have for populating the Mookodi lists before building more logic on top of it.
2. Think about and build the first link from ATLAS to SALT (populating a SALT list).
3. Expand the logic with more data analysis (finding the light-curve peak) to populate a new "Mookodi near-peak" list.

### People

In additiona to Ken and Stephen, key people are:
- Nic Erasmus: He is in charge of the robotisation of Mookodi and our link there
- Simon de Wet: He is our contact for SALT and is involved in the Mookodi link too. He is the scientist eyeballing most of the data at the moment


## General overview of the current process:

1. New transient candidates are discovered in ATLAS 
2. My Virtual Research Assistant ranks the candidates from 0 (bad) to 10 (good)
3. If a candidate is located <100Mpc of the Earth and gets a score >8.5 it gets appended to a custom list on the ATLAS Transient server called Mookodi Telescope Follow up
4. When a candidate in that list reaches a magnitude that is bright enough (17 mag and brighter) I have a script that puts it in another list "Mookodi Telescope Live Followup (Experimental)" which is the one that the telescope is listening to. 

This is an inefficient workflow because it just grew itteratively. But the things that will not change are this:
- I will write scripts that find interesting targets in the ATLAS stream 
- I will populate custom lists with these targets
- Nic and Simon will then use the ATLAS API Client to read from those list and populate their telescope sheduler. No need for us to learn their telescope API.

## Where the code lives

These pipelines live on db1 in Oxford under the atlas user but we will develop them on my local machine (here).
Since it's all API calls we can develop locally as there is no remote data or infra that we need. 

## Notes:
- Magnitudes are astronomre units that are logarithmic and run backwards. Mag 17 is brighter than mag 18. When I say "maximum magnitude" I usually mean "brightest", so the lower numbre. 
