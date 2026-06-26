# Scope history and future

This started as just a simple script for me to fill a list on the ATLAS Web server for Mookodi to get its targets. 

Now we want several lists for Mookodi plus a SALT integration. 

We need an actual structure and proper tests. 

- Should this be an independent subpackage or part of the ATLAS VRAs? 
- Is it worth deploying with containers (k8s?) on the server? contenerising is scary and messy but wiht claude it might work and make my life easier?


# Design 

## Data Journey in ATLAS Web Server

When an alert passes the CNN real bogus classifier and the VRA garbage collector, it is either put in the eyeball list or the Fast Track list depending on the distance to the host galaxy associated with the transient. Fast Track for <100Mpc.

Humans will eyeball these lists typically and when they are judged good they are promoted by a human to the "Good" list. With objects in the Fast Track list if they have VRA score >8.5 they are also added to the custom list called "Mookodi List" automatically BEFORE a human looks at it. Objects cannot be in the eyeball or Fast Track list AND the Good list simulataneously because these are all core lists. 

The objects CAN be in multiple custom lists though, and they do not get moved from the custom lists when they are moved form one core list to another (eyeball to good for example). 

This is important because the Mookodi custom list is then a sort of "staging area" and we wait forthese transients reach mag brighter than 17 to be added to the Mookodi Live List (Experimental). It should be renamed to Mookodi Young Transients (not for us to do - Ken will do it on the web server).

## Mookodi Young Transient list

The current two step process feels inefficient but having a staging area with a custom list whose state doesn't change when people eyeball feels like a good idea actually. 

## Mookodi Peak Transient List

The staging area can also be used by the Mookodi Peak transient List, we'll have to make sure that the objects are not removed when there is a TNS classification though (these will be ignored by the script that populations the Mookodi Young Transient List). 

## SALT List

SALT can see deeper than ATLAS so there is no need to wait for things to get bright enough. No staging list needed?
The source should be anything in the Fast Track List with VRA Score >8.5 and everything in the eyeball list with score >9 and <10.0. These numbers shouldn't be hard coded they should be options we can change. 

---

# Project Status & Decisions Log (Claude-maintained — updated as design progresses)

_Last updated: 2026-06-17. See `~/projects-status-for-claude.md` for the cross-project view; this section is the detailed handoff for resuming design work on this file specifically._

## Confirmed facts (data model)

- Full `dict_list_id` core-vs-custom namespace mapping confirmed live 2026-06-17 (recorded in detail in `atlas_sao/docs/atlasapiclient_reference.md`):
  - **Core detection-list IDs** (mutually exclusive — one object is in exactly one): `garbage=0, follow_up=1, good=2, possible=3, eyeball=4, attic=5, stars=6, agn=7, fasttrack=8, movers=9, magellanic_clouds=10, pm_stars=11, galcand=12, duplicates=13`.
  - **Custom list IDs** (an object can be in many simultaneously): `mookodi=2, mookodi_live=16, cv=40, mdwarf=56, heloise=72, vra=73, dummy=999`, plus **salt=14** (Ken-created server-side, not yet added to `dict_list_id` — see `atlasapiclient#45`).
  - Note `good` (core, =2) and `mookodi` (custom, =2) share the number 2 but are unrelated — different ID namespaces.
- **VRA score is already in the payload we fetch for other reasons**: `entry['object']['vra']` from `RequestSingleSourceData`/`RequestMultipleSourceData`. Confirmed live against real ATLAS ID `1193736770311803200` (`vra=6.2587`, matched the web server's displayed 6.26). No need for a separate `RequestVRAScores` call.
- `RequestVRAToDoList` is **not** a useful source for Peak/SALT candidates — it's specifically objects not yet garbaged or human-labelled; anything we want for Peak/SALT has already passed that stage.

## Open design questions (unresolved — pick up here next session)

1. **Staging list (`object_group=2`, `'mookodi'`) growth.** Peak logic needs TNS-classified objects to *stay* in staging so it can still evaluate them for peak brightness — but the current Young Transient cleanup script removes on classification alone. If that changes to garbage-only removal, nothing currently retires old classified objects from staging, so it grows forever. H considered a "stale entries" dashboard but suspects that's overkill. **Current decision: let it grow for now, delete/retirement strategy TBD.**
2. **Peak Transient List is a brand-new 3rd custom list** (distinct from staging=2 and Live/Young=16). `object_group_id` not yet known — needs Ken to create it server-side (same as he already did for SALT, list 14).
3. **SALT list cleanup logic:** drop from queue once TNS-classified. Possibly also an external "consumed" signal from Simon once he's processed it — mechanism TBD.
4. **SALT source criteria, current best understanding:**
   - Fast Track core list (`detection_list_id=8`) + VRA score > 8.5
   - Eyeball core list (`detection_list_id=4`) + VRA score > 9, **no upper bound** (H corrected herself: score=10 just means "in TNS", not "classified" — the real eyeball gate is "not yet classified", not a score ceiling)
   - **Open question:** should Fast Track also explicitly require "not yet classified"? Unlike the Mookodi staging list (object_group=2), which only contains not-yet-classified objects as a *side effect* of `mookodiListWizard.py`'s continuous cleanup, a SALT query reading directly off the Fast Track core list would NOT automatically inherit that filtering. Needs an explicit decision + implementation.
   - Both thresholds (8.5, 9) must be configurable, not hardcoded.
5. **No staging list for SALT** — confirmed single flat custom list (14), unlike Mookodi's two-step staging→live structure.
6. **Architecture question (H's own, still open):** independent subpackage, or live inside the ATLAS VRA repo? Not yet decided.

## What's already done

- `atlasapiclient` issues #42/#43 fixed, merged via PR #44 (`get_response()` not returning data on write/delete; `WriteToCustomList` chunking bugs).
- `mookodiListWizard.py` refactored: one-at-a-time wrapper functions removed, single batched call per list (`chunk_size=25` on removes), one-line logs, no-op on empty input, new test file `tests/test_mookodi_list_wizard.py` (4 passing tests).

## Next session

Start with open questions #1 and #4 above, then move toward a written design for Peak Transient List + SALT List logic (full brainstorming pass, not skipped this time since scope is bigger than the refactor was).

## H new comments to be sorted
- Should add a new condition to fill the Mookodi list: if the object is in the Good List (or start with Follow up list) and reaches mag 17 or brighter AND is not TNS classified, add to Mookodi Live list. The Followup list has the advantage of getting cleaned up by us on fridays, but it might not be complete. The Good list would be complete but we would need a new condition to clean up the list. FOR A FIRST GO LET'S STICK TO FOLLOW-UP LIST CHECK + TNS not classified. This is easiest.  
