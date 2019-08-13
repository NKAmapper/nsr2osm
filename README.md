# nsr2osm
Extracts public transportation stops from the Norwegian National Stop Register (NSR) at Entur

### Usage ###

#### nsr2osm ####

<code>python nsr2osm.py [-upload|-manual]</code>

* This program is used for updating bus stops and bus stations (only) after the initial import
  * Creates *nsr_update.osm* file with updated stop places which may be uploaded to OSM
  * Creates *nsr_update_log.txt* file with log of modifications done to OSM file
  * Only bus stops and stations where *nsr2osm* did the last edit in OSM are updated
  * If edited by someone else in OSM, the NSR stop place is included as a reference (if location differs by 1 meter or more, or if the NSR tags *name*, *ref* etc have been modified)
* Options:
  * The *-upload* option will make a direct upload to OSM from the *nsr2osm* import account
  * The *-manual* option will just create the two local files for manual insepction in JOSM
* Examples of useful searches in JOSM:
  * <code>new -NSR_REFERENCE</code> - New stop places to be uploaded
  * <code>modified -new -NSR_REFERENCE</code> - Modified stop places to be uploaded
  * <code>DELETE</code> - Stop places to be deleted (manual deletion in JOSM)
  * <code>EDIT > 2019-03-30</code> - Stop places edited by a user other than the import user *nsr2osm* after given date. Contains tags with distance moved from NSR position (if any) and name in NSR (if different than name given by user)
  * <code>OTHER > 2010</code> - Stop places not in NSR with last edit after given date
  * <code>NSR_REFERENCE</code> - Stop places in NSR which have been edited by a user other than the import user *nsr2osm*. Note that a search for EDIT is usually better.
* Manual uploading:
  * Before uploading you may want to use the *Download parent ways and relations* function in JOSM to avoid conflicts
  * Use *Upload selection* or *Purge* functions in JOSM to avoid uploading all elements to JOSM
  * Please remember to remove the extra information tags in capital letters before uploading to OSM

#### nsr2osm_dump ####

<code>python nsr2osm_dump.py [county]</code>

* This program is used for generating a complete OSM file from the NSR NeTEx files, for the initial import or later inspection
* Creates *nsr_current.osm* file with all stop places in Norway, or for given county
* Use name of county to produce OSM file for that county, e.g. "Vestfold"
* Use "Norge" to produce OSM file for the whole country

### Notes ###

* Import plan: [Bus stop import Norway](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Bus_stop_import_Norway)
* Generated files: [OSM files](https://drive.google.com/drive/folders/1pkHcNvmHoRWHHTrnrIWpC--cCFmPbkXL?usp=sharing)
