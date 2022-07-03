# nsr2osm
Extracts public transportation stops from the Norwegian National Stop Register (NSR) NeTEx feed at Entur.

[![Run nsr2osm_dump.py every morning](https://github.com/NKAmapper/nsr2osm/actions/workflows/main.yml/badge.svg)](https://github.com/NKAmapper/nsr2osm/actions/workflows/main.yml)
- Github action is run every morning to produce `nsr_current.osm` and upload as artifact to Github + upload to [Google Drive folder](https://drive.google.com/drive/folders/1pkHcNvmHoRWHHTrnrIWpC--cCFmPbkXL?usp=sharing).

### Usage ###

#### nsr2osm ####

<code>python nsr2osm.py [-upload|-manual]</code>

* This program is used for updating (coordinates, name and ID of) bus stops and bus stations (only) after the initial import.
  * Creates a *nsr_update.osm* file with updated stop places which may be uploaded to OSM.
  * Creates a *nsr_update_log.txt* file with log of modifications done to OSM file.
  * Only bus stops and stations last edited by *nsr2osm* in OSM are updated.
  * If edited by someone else in OSM, the NSR stop place is included as a reference (if location differs by 1 meter or more, or if the NSR tags *name*, *ref* etc. have been modified).
  * Bus stops which have not been used by any route for one year are removed.
* Options:
  * The *-upload* option uploads directly to OSM from the *nsr2osm* import account.
  * The *-manual* option just creates the two local files for manual insepction in JOSM.
* Examples of useful searches in JOSM:
  * <code>new -NSR_REFERENCE</code> - New stops to be uploaded.
  * <code>modified -new -NSR_REFERENCE</code> - Modified stops to be uploaded.
  * <code>DELETE</code> - Stops to be deleted (manual deletion in JOSM).
  * <code>EDIT > 2019-03-30</code> - Stops edited by a user other than the importing user *nsr2osm* after given date. Contains tags with distance moved from NSR position (if any) and name in NSR (if different than name given by user).
  * <code>TOUCH > 2019-03-30</code> - Stops edited by a user other than the importing user *nsr2osm* after given date. The user did not edit coordiante nor name. Only in manual mode. The stops will be touched by *nsr2osm* during next upload.
  * <code>OTHER > 2010</code> - Stops not in NSR with last edit after given date.
  * <code>NSR_REFERENCE</code> - Stops in NSR which have been edited by a user other than the importing user *nsr2osm*. Note that a search for "EDIT" is usually better.
* Manual uploading:
  * Before uploading you may want to use the *Download parent ways and relations* function in JOSM to avoid conflicts.
  * Use *Upload selection* or *Purge* functions in JOSM to avoid uploading all elements to JOSM.
  * Please remember to remove the extra information tags in capital letters before uploading to OSM.

#### nsr2osm_dump ####

<code>python nsr2osm_dump.py [county]</code>

* This program is used for generating a complete OSM file from the NSR NeTEx files, for the initial import or later inspection.
  * Creates a *nsr_current.osm* file with all stop places in Norway, or for given county.
  * The *ROUTE* tag contains information about each route for a given stop, including operator and inbound/outbound information.
* Mandatory input parameter:
  * Use name of county to produce OSM file for that county, e.g. "Rogaland".
  * Use "Norge" to produce OSM file for the whole country.

### Changelog

nsr2osm.py
* 1.7: Keep bus stops for one year after last used by route.
* 1.6: Delete bus stops not used by any route.
* 1.5: Code converted to Python 3.

nsr2osm_dump.py
* 1.0: Code converted to Python 3. Also fix bug in source data regarding short/long route names. 

### Notes ###

* Import plan: [Bus stop import Norway](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Bus_stop_import_Norway).
* Generated files: [OSM files](https://drive.google.com/drive/folders/1pkHcNvmHoRWHHTrnrIWpC--cCFmPbkXL?usp=sharing).
