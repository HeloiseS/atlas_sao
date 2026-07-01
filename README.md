# ATLAS SAO pipelines

## Mookodi
TBW

### Mookodi Transients at Peak
For now we will use a dumb placeholder: brighter than 16 mag. Why? because for mookodi we usually target things within 100 Mpc. that's distance modulus 35, so absolute mag 19. That's the peak of a Ia SN at 100Mpc. So we won't be filling up the list with things that are too distant. Also 16th and brighter is a really good SNR for mookodi, so we'll only be targetting bright things, nearby, most likely near peak. And those that are so nearby that they are not near peak will be much less numerous because the volume is much smaller. So this is a great place to start using the list, then I'll see what targets end up "contaminating" the list and I'll refine later.

## SALT
TBW

## Code review checklist 

HFS Review summary:

- [x] `atlas_sao/db.py` - commented and requested to parse connections instead of creating them, but only because i am concerned about leaving connections open. We can discuss this decision. 
- [x] `atlas_sao/refreshXtgal.py` - refactor needed on the logic to upsert. Details in comments; ask if you need a better description. 
- Related: I removed VRA_SCORE_WHEN_ADDED FLOAT, VRA_SCORE_NOW FLOAT from schema. I realised it was unnecessary for that table. Database and code NOT UPDATED YET to reflect that change. 
- [x] `atlas_sao/mookodiPeakListWizard.py` - all good
- [x] `atlas_sao/mookodiListWizard.py` - all good
- [x] `atlas_sao/saltListWizard.py` - all good



## Db schema draft


```SQL
CREATE XTGAL_3MNTHS (
ATLAS_ID INT
ACTIVE BOOL
DATE_ADDED
LAST_MAG FLOAT
LAST_MAG_ERR FLOAT
LAST_MAG_FILT FLOAT
TIMESTAMP 
);

CREATE BK_YOUNG_FAST_TRACK(
ATLAS_ID INT
DATE_ADDED
DATE_REMOVED
VRA_SCORE_WHEN_ADDED
VERSION
);

CREATE BK_YOUNG_NOT_FAST_TRACK(
);

CREATE BK_PEAK(
);
```
