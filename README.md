# nsr2osm
Extracts public transportation stops from the Norwegian National Stop Register at Entur

### Usage ###

#### nsr2osm ####

<code>python nsr2osm.py</code>

* For bus stations and bus stops only
* Creates *nsr_update.osm* file with updated stop places which may be uploaded to OSM
* Creates *nsr_update_log.txt* file with log of modifications done to OSM file
* Examples of useful searches in JOSM:
  * <code>new -NSR_REFERENCE</code> - New stop places to be uploaded (remember to delete information tags with capital letters)
  * <code>modified -new -NSR_REFERENCE</code> - Modified stop places to be uploaded
  * <code>DELETE</code> - Stop places to be deleted (manual deletion in JOSM)
  * <code>EDIT > 2019-03-30</code> - Stop places edited by a user other than the import user *nsr2osm* after given date. Contains tags with distance moved from NSR position (if any) and name in NSR (if different than name given by user)
  * <code>OTHER > 2010</code> - Stop places not in NSR with last edit after given date
  * <code>NSR_REFERENCE</code> - Stop places in NSR which have been edited by a user other than the import user *nsr2osm* (a search for EDIT is better)
* Use *Upload selection* or *Purge* functions in JOSM to avoid uploading all elements to JOSM

#### nsr2osm_dump ####

<code>python nsr2osm_dump.py [county]</code>

* Creates *nsr_current.osm* file with all stop places in Norway, or for given county
* Use name of county to produce OSM file for that county, e.g. "Vestfold"
* Use "Norge" to produce OSM file for the whole country

### Notes ###

* Import plan: [Bus stop import Norway](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Bus_stop_import_Norway)
* Generated files: [OSM files](https://drive.google.com/drive/folders/1pkHcNvmHoRWHHTrnrIWpC--cCFmPbkXL?usp=sharing)
