# ATLAS SAO pipelines

Last Updated: 2026-07-08

# User References

There are currently 3 lists of interest:
- **Mookodi Live List (Custom List 16)** | **[Working]** : Young Transients within 100 Mpc that have not yet been classified, with VRA Score > 8.5
- **Salt List (Custom List 14)** | **[MVP]**: Young Transients that have not yet been classified, with VRA Score > 9.0 and that are not Orphans. 
- **Mookodi Peak Transients (Custom List 17)** | **[Dev]**: Transients "at peak". Current definition of "at peak" is: the last 3 lc points are all real detections brighter than 16.9 mag (allowing for their 1-sigma error bar). This was for devs purposes and will be refined. 

---

# Dev References

## Mookodi Live List: Young Fast Track Transients
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


## SALT List 

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

## Mookodi Transients at Peak

Custom List: 17


**Constraints**
- Already classified as good
- Mag Threshold (will need better "at peak" descriptor)

For now we will use a dumb placeholder: **brighter than 16.9 mag**. Why? because for mookodi we usually target things within 100 Mpc. that's distance modulus 35, so absolute mag 19. That's the peak of a Ia SN at 100Mpc. So we won't be filling up the list with things that are too distant. Also 16.9th and brighter is a really good SNR for mookodi, so we'll only be targetting bright things, nearby, most likely near peak. And those that are so nearby that they are not near peak will be much less numerous because the volume is much smaller. So this is a great place to start using the list, then I'll see what targets end up "contaminating" the list and I'll refine later.

**2026-07-20 update**: 16 mag was too restrictive (missed genuine near-peak objects between 16 and 16.9), and checking only the single latest lc point wasn't restrictive enough — a single bogus bright detection could get an object onto the list. Fixed both: threshold moved to 16.9 mag, and now we require the **last 3** lc points to each be real detections (not non-detections) that are brighter than 16.9 allowing for their 1-sigma error bar (`mag - magerr < 16.9`). If the last 3 points are non-detections, or any of them fails that check, the object is removed from the list (or never added in the first place). See `is_at_peak()` in `mookodiPeakListWizard.py`.

**2026-07-21 update ([#27](https://github.com/HeloiseS/atlas_sao/issues/27))**: the "last 3 points" check above only looked at `lc`, but non-detections don't show up there — they live in a separate `lcnondets` field (limiting mag only, no mag/magerr). So an object with old bright `lc` points and thousands of recent non-detections in `lcnondets` was staying on the list forever, since those non-detections were invisible to the check. Fixed by merging `lc` and `lcnondets` on mjd before taking the last 3 points, so a recent non-detection now correctly counts as one of the most recent visits.


**Inputs**
- Objects that have been classified as good in the last X weeks (i.e are set as Active in `xtgal_3mnths` table.)

**Script**: `refreshXtgal.py`
- Finds all atlas\_ids in VRA Scores table (`tsc_vra_scores`) which have been labeled as extragalacitc by a person (`preal == 1.0`, `pgal==0.0`).
- Puts them in the `xtgal_3mnths` table with Active = 1. 
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

### `xtgal_3mnths`

```
id    atlas_id             active  date_added           last_mag  last_mag_err  last_mag_filt  timestamp          
----  -------------------  ------  -------------------  --------  ------------  -------------  -------------------
4440  1132830610110316600  1       2026-07-08 08:47:55                                         2026-07-08 08:47:55

```



# Heloise's Quick Notes

To find the number of objects (unique) added to a list on each day you can do:

```sql
select substr(date_added, 1, 10) as day_added, count(distinct(atlas_id)) from bk_peak group by day_added;
```
