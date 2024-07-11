#!/usr/bin/env python3
# -*- coding: utf8

# nsr2osm
# Converts public transportation stops from Entur NeTex files and matches with OSM for update in JOSM
# Reads NSR data from Entur NeTEx file (XML)
# Usage: stop2osm.py [-manual | -upload]
# Creates OSM file with name "nsr_update.osm" and log file "nsr_update_log.txt"
# Uploads to OSM if -upload is selected


import sys
import json
import zipfile
import csv
import math
import copy
import time
import datetime
import base64
import os.path
import urllib.request, urllib.error, urllib.parse
from io import BytesIO, TextIOWrapper
from xml.etree import ElementTree as ET


version = "2.0.0"

debug = True

request_header = {"User-Agent": "nsr2osm"}

username = "nsr2osm"  # Upload to OSM from this user

osm_api = "https://api.openstreetmap.org/api/0.6/"  # Production database

overpass_api = "https://overpass-api.de/api/interpreter"
#overpass_api = "https://overpass.kumi.systems/api/interpreter"

history_filename = "~/Google Drive/Stoppested/nsr_history.json"

exclude_counties = []  # Omit counties (two digit ref's)
#exclude_counties = [03", "11", "15", "18", "30", "34", "38", "42", "46", "50", "54"]

user_whitelist = ["nsr2osm", "ENTUR Johan Wiklund", "Wulfmorn"]  # Only modify stops in OSM if last edit is from these users

quays_abroad = ["101150", "15343"]  # Quays just outside of Norway border (to avoid duplicates)

out_filename = "nsr_update"

max_distance = 1.0  # Nodes relocated more than or equal to this distance will get new coordinates (meters)

ptv1 = False  # True to maintain PTv1 tagging, unless stop is part of PTv2 relation
ptv1_modify = True  # True to maintain PTv1 tagging when stop/station is updated for other reasons

# Keys used for manual inspection
manual_keys = ["EDIT", "DISTANCE", "NSR", "NSR_NAME", "NSR_REFERENCE", "USER", "OTHER", "MUNICIPALITY", "VERSION", "STOPTYPE", "SUBMODE", "NSRNOTE", "DELETE", "LAST_USED"]



# Open file/api, try up to 5 times, each time with double sleep time

def open_url (url):

	delay = 60  # seconds
	tries = 0
	while tries < 5:
		try:
			return urllib.request.urlopen(url)
		except urllib.error.HTTPError as e:
			if e.code in [429, 503, 504]:  # Too many requests, Service unavailable or Gateway timed out
				if tries  == 0:
					message ("\n") 
				message ("\rRetry %i in %ss... " % (tries + 1, delay * (2**tries)))
				time.sleep(delay * (2**tries))
				tries += 1
				error = e
			elif e.code in [401, 403]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Unauthorized or Blocked
				sys.exit()
			elif e.code in [400, 409, 412]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Bad request, Conflict or Failed precondition
				message ("%s\n" % str(e.read()))
				sys.exit()
			else:
				raise

		except urllib.error.URLError as e:  # Mostly "Connection timed out"
			if tries  == 0:
				message ("\n") 
			message ("\r\tRetry %i in %ss... " % (tries + 1, delay * (2**tries)))
			time.sleep(delay * (2**tries))
			tries += 1
	
	message ("\nHTTP error %i: %s\n" % (error.code, error.reason))	
	sys.exit()



# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()



# Log query results

def log(log_text):

	if debug:
		log_file.write(log_text)



# Compute approximation of distance between two coordinates, in meters
# Works for short distances
# Format: (lon, lat)

def compute_distance (p1, p2):

	lon1, lat1, lon2, lat2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
	x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
	y = lat2 - lat1
	return round(6371000 * math.sqrt( x*x + y*y ), 1)  # One decimal



# Generate OSM/XML for one OSM element, including for changeset
# Parameter:
# - element:	Dict of OSM element in same format as returned by Overpass API
#				'action' contains 'create', 'modify' or 'delete' (or is not present)

def generate_osm_element (element):

	if element['type'] == "node":
		osm_element = ET.Element("node", lat=str(element['lat']), lon=str(element['lon']))

	elif element['type'] == "way":
		osm_element = ET.Element("way")
		if "nodes" in element:
			for node_ref in element['nodes']:
				osm_element.append(ET.Element("nd", ref=str(node_ref)))

	elif element['type'] == "relation":
		osm_element = ET.Element("relation")
		if "members" in element:
			for member in element['members']:
				osm_element.append(ET.Element("member", type=member['type'], ref=str(member['ref']), role=member['role']))

	if "tags" in element:
		for key, value in iter(element['tags'].items()):
			osm_element.append(ET.Element("tag", k=key, v=value))

	osm_element.set('id', str(element['id']))
#	osm_element.set('visible', 'true')

	if "user" in element:  # Existing element
		osm_element.set('version', str(element['version']))
		osm_element.set('user', element['user'])
		osm_element.set('uid', str(element['uid']))
		osm_element.set('timestamp', element['timestamp'])
		osm_element.set('changeset', str(element['changeset']))

	if "action" in element and element['action'] in ["create", "modify"]:
		osm_element.set('action', 'modify')

	osm_root.append(osm_element)

	if upload and "action" in element:
		action_element = ET.Element(element['action'])
		action_element.append(osm_element)
		upload_root.append(action_element)



# Output stops
# Parameters:
# - action:		new/modify/delete/user edit/other stop/nsr reference
# - stop_type:	station/quay
# - nsr_ref:	Unique station or quay reference in NSR, or None
# - osm_stop:	Dict of OSM element from Overpass, or None
# - nsr_stop:	Dict of NSR station or quay generated from Entur input file, or None
# - distance:	Computed distance between coordinates for stop in NSR vs OSM, or None

def produce_stop (action, stop_type, nsr_ref, osm_stop, nsr_stop, distance):

	global node_id, osm_data  # osm_way_nodes, osm_relation_members

	log ("\n\n%s: %s #%s\n" % (action.upper(), stop_type, nsr_ref))
	if distance > 0:
		log ("  Moved %.1f meters\n" % distance)

	# Create new stop or reference stops
	# Reference stops are not for uploading to OSM; included to show NSR coordinate and content if user has edited stop in OSM

	if action in ["new", "nsr reference"]:
		node_id -= 1

		entry = {
			'id': node_id,
			'lat': nsr_stop['lat'],
			'lon': nsr_stop['lon'],
			'type': "node",
			'tags': {}
		}

		if stop_type == "station":
			entry['tags']['ref:nsrs'] = nsr_ref			
		elif stop_type == "quay":
			entry['tags']['ref:nsrq'] = nsr_ref

		for key in ["name", "official_name", "ref", "unsigned_ref"]:
			if key in nsr_stop:
				entry['tags'][key] = nsr_stop[key]

		for key in ["municipality", "submode", "nsrnote", "stoptype", "version"]:
			if key in nsr_stop:
				entry['tags'][key.upper()] = nsr_stop[key]

		if action == "new":  # Do not include main tags for reference elements
			entry['action'] = "create"
			if stop_type == "station":
				entry['tags']['amenity'] = "bus_station"
			elif stop_type == "quay":
				entry['tags']['highway'] = "bus_stop"

		else:
			entry['tags']['NSR_REFERENCE'] = "yes"  # Mark element as reference only (not for update)

		osm_data['elements'].append(entry)

		log (json.dumps(nsr_stop, indent=2, ensure_ascii=False))
		log ("\n")

	# Modify stop

	elif action in ["modify", "relocate"]:

		# Detach stop if it is a node in a way (the extra node is not counted)

		osm_stop['action'] = "modify"

		if osm_stop['id'] in osm_way_nodes:
			entry = copy.deepcopy(osm_stop)
			del entry['tags']
			osm_data['elements'].append(entry)
#			stops_new += 1

			node_id -= 1
			osm_stop['id'] = node_id
			osm_stop['action'] = "create"
			log ("  Detach stop node from way\n")

		# Modify tags

		if osm_stop['type'] == "node" and action == "relocate" or osm_stop['action'] == "create":
			osm_stop['lat'] = nsr_stop['lat']
			osm_stop['lon'] = nsr_stop['lon']
			if distance > 0:
				osm_stop['tags']['DISTANCE'] = "%.1f" % distance

		if stop_type == "station":
			osm_stop['tags']['amenity'] = "bus_station"
			osm_stop['tags']['ref:nsrs'] = nsr_ref
			if "highway" in osm_stop['tags'] and osm_stop['tags']['highway'] == "bus_stop":
				del osm_stop['tags']['highway']
				log ("  Change tagging from 'highway = bus_stop' to 'amenity = bus_station'\n")
			check_keys = ["name", "route_ref"]
			if ptv1_modify and osm_stop['id'] not in osm_ptv2_members:
				check_keys += ['public_transport', 'bus']

		elif stop_type == "quay":
			osm_stop['tags']['highway'] = "bus_stop"
			osm_stop['tags']['ref:nsrq'] = nsr_ref
			if "amenity" in osm_stop['tags'] and osm_stop['tags']['amenity'] == "bus_station":
				del osm_stop['tags']['amenity']
				log ("  Change tagging from 'amenity = bus_station' to 'highway = bus_stop'\n")
			check_keys = ["name",  "official_name", "ref", "unsigned_ref", "route_ref"]
			if ptv1_modify and osm_stop['id'] not in osm_ptv2_members:
				check_keys += ['public_transport', 'bus']

		for key in check_keys:
			if key in nsr_stop:
				if key in osm_stop['tags']:
					if osm_stop['tags'][key] != nsr_stop[key]:
						log ("  Change tag '%s' from '%s' to '%s'\n" % (key, osm_stop['tags'][key], nsr_stop[key]))
				else:
					log ("  New tag '%s = %s'\n" % (key, nsr_stop[key]))
				osm_stop['tags'][key] = nsr_stop[key]
			elif key in osm_stop['tags']:
				log ("  Delete tag '%s = %s'\n" % (key, osm_stop['tags'][key]))
				del osm_stop['tags'][key]

	# Mark stop as deleted (for manual deletion in JOSM)

	elif action == "delete":

		osm_stop['tags']['DELETE'] = "yes"
		log (json.dumps(osm_stop, indent=2, ensure_ascii=False))
		log ("\n")

		# Keep element if element belongs to or is itself a way or relation

		if (upload and ((osm_stop['id'] in osm_way_nodes)
						or (osm_stop['id'] in osm_relation_members)
						or ("nodes" in osm_stop) or ("members" in osm_stop))):

			osm_stop['tags'] = {}
			if osm_stop['id'] in osm_ptv2_members:
				osm_stop['tags']['fixme'] = "Relocate bus stop? (bus stop not used in NSR routes)"
				log ("  Check %s #%s (deleted stop/station had way or relation dependencies)\n" % (osm_stop['type'], osm_stop['id']))
				message ("  *** Check %s #%s (deleted stop/station had way or relation dependencies)\n" % (osm_stop['type'], osm_stop['id']))
			osm_stop['action'] = "modify"	

		else:
			osm_stop['action'] = "delete"

	# Mark stop as edited by user (for information only)

	elif action == "user edit":

		osm_stop['tags']['EDIT'] = osm_stop['timestamp'][0:10]
		osm_stop['tags']['USER'] = osm_stop['user']

		if distance > 0:
			osm_stop['tags']['DISTANCE'] = "%.1f" % distance  # Include distance from NSR coodinate if different

		osm_name = ""
		nsr_name = ""
		if "name" in nsr_stop:
			nsr_name = nsr_stop['name']
		if "name" in osm_stop['tags']:
			osm_name = osm_stop['tags']['name']

		if osm_name != nsr_name:
			log ("  User tagged 'name' as '%s'; in NSR '%s'\n" % (osm_name, nsr_name))
			if nsr_name:
				osm_stop['tags']['NSR_NAME'] = nsr_name  # Include NSR name if different

		log (json.dumps(osm_stop, indent=2, ensure_ascii=False))
		log ("\n")

	# Include bus_stop or bus_station which is not present in NSR (without ref:nsrs/nsrq tags)

	elif action == "other stop":

		osm_stop['tags']['OTHER'] = osm_stop['timestamp'][0:10]
		osm_stop['tags']['USER'] = osm_stop['user']
		log (json.dumps(osm_stop, indent=2, ensure_ascii=False))
		log ("\n")

	# Extra information about when stops were last used by any route

	if (stop_type == "quay" and nsr_ref is not None and osm_stop is not None
			and nsr_ref not in route_quays and nsr_ref in history['quays'] and "date" in history['quays'][ nsr_ref ]):
		osm_stop['tags']['LAST_USED'] = history['quays'][ nsr_ref ]['date']



# Read stops from OSM for county, match with NSR and output result
# Paramters:
# - county_id:		Two digit county reference
# - county_name:	Full name of county

def process_county (county_id, county_name):


	# Check if tags in NSR and OSM are differnt

	def different_tags(nsr_stop, osm_tags, check_tags):

		for tag in check_tags:
			osm_tag = ""
			nsr_tag = ""
			if tag in nsr_stop:
				nsr_tag = nsr_stop[ tag ]
			if tag in osm_tags:
				osm_tag = osm_tags[ tag ]

			if osm_tag != nsr_tag:
				return True

		return False


	global stops_total_modify, stops_total_delete, stops_total_edits, stops_total_others, stops_new
	global osm_data

	message ("\nLoading #%s %s county... " % (county_id, county_name))
	log ("\n\n*** COUNTY: %s %s\n" % (county_id, county_name))

	# Load stops from Overpass, plus any parent ways/relations and children

	query = ('[out:json][timeout:90];'
			'(area["name"="%s"][admin_level=4];)->.a;'
			'('
				'nwr["amenity"="bus_station"](area.a);'
				'nwr["highway"="bus_stop"](area.a);'
			')->.b;'
			'(.b; .b >; .b <;);'
			'out center meta;' % county_name)

	osm_data = {'elements': []}
	while not osm_data['elements']:  # May deliver empty result
		request = urllib.request.Request(overpass_api + "?data=" + urllib.parse.quote(query), headers=request_header)
		file = open_url(request)
		osm_data = json.load(file)
		file.close()

	# Make lists of all stop nodes witch are part of ways and relations

	osm_way_nodes.clear()
	osm_relation_members.clear()
	osm_ptv2_members.clear()
	count_relations = 0

	for element in osm_data['elements']:
		if "nodes" in element:
			for node in element['nodes']:
				osm_way_nodes.append(node)
		if "members" in element:
			count_relations += 1
			for member in element['members']:
				osm_relation_members.append(member['ref'])
				if "tags" in element:
					if "public_transport" in element['tags'] or "type" in element['tags'] and element['tags']['type'] == "route":
						osm_ptv2_members.append(member['ref'])

	message ("Connected to %i nodes, %i relations\n" % (len(osm_way_nodes), count_relations))

	# Iterate stops from OSM and discover differences between NSR and OSM
	# The dict osm_data will be modified to include all stops to be output
	# When done, only NSR stops which did not get a match remain in NSR stations/quays dicts

	stops_nsr = 0
	stops_osm = 0
	stops_modify = 0
	stops_delete = 0
	stops_new = 0
	stops_edit = 0
	stops_other = 0
	stops_history = 0

	index = 0
	the_end = False
	end_element = osm_data['elements'][-1]  # Iteration will end at this stop
	osm_stop = None

	while not(the_end):
		osm_stop = osm_data['elements'][index]
		index += 1
		if osm_stop == end_element:
			the_end = True

		if "tags" in osm_stop:

			tags = osm_stop['tags']

			# Stations

			if "ref:nsrs" in tags:

				stops_osm += 1
				nsr_ref = tags['ref:nsrs']
				if nsr_ref in stations:

					stops_nsr += 1
					station = stations[nsr_ref]
					relocate = False
					nsr_relocate = False  # Will become True if location in NSR changed since last check
					tag_modify = False
					extra_distance = 0

					# Check location

					if "center" in osm_stop:
						distance = compute_distance((osm_stop['center']['lon'], osm_stop['center']['lat']), (station['lon'], station['lat']))
						extra_distance = 100
					else:
						distance = compute_distance((osm_stop['lon'], osm_stop['lat']), (station['lon'], station['lat']))

					if distance >= max_distance + extra_distance:
						relocate = True
						if (nsr_ref in history['stations'] and "point" in history['stations'][ nsr_ref ]
								and history['stations'][ nsr_ref ]['point'] != [station['lon'], station['lat']]):
							nsr_relocate = True
							stops_history += 1

					# Check tags

					check_tags = ["name"]
					if ptv1 and osm_stop['id'] not in osm_ptv2_members:
						check_tags += ["public_transport", "bus"]

					if different_tags(station, tags, check_tags):
						tag_modify = True 

					# Modify if name difference or if relocated in NSR or if last edit is by user in whitelist, else include for information

					if relocate or tag_modify:
						if nsr_relocate or relocate and (osm_stop['user'] in user_whitelist or tag_modify):
							produce_stop ("relocate", "station", nsr_ref, osm_stop, station, distance)
							stops_modify += 1
						elif tag_modify:
							produce_stop ("modify", "station", nsr_ref, osm_stop, station, distance)								
							stops_modify += 1
						else:
							produce_stop ("user edit", "station", nsr_ref, osm_stop, station, distance)
							if distance > 0:
								produce_stop ("nsr reference", "station", nsr_ref, None, station, 0)  # Output NSR stop for reference only
							stops_edit += 1

					del stations[ nsr_ref ]

				else:
					produce_stop ("delete", "station", nsr_ref, osm_stop, None, 0)
					stops_delete += 1

			# Quays

			elif "ref:nsrq" in tags:

				stops_osm += 1
				nsr_ref = tags['ref:nsrq']
				if nsr_ref in quays:

					stops_nsr += 1
					quay = quays[nsr_ref]
					relocate = False
					nsr_relocate = False
					tag_modify = False
					extra_distance = 0

					# Check location

					if "center" in osm_stop:
						distance = compute_distance((osm_stop['center']['lon'], osm_stop['center']['lat']), (station['lon'], station['lat']))
						extra_distance = 10
					else:
						distance = compute_distance((osm_stop['lon'], osm_stop['lat']), (quay['lon'], quay['lat']))

					if distance >= max_distance + extra_distance:
						relocate = True
						if (nsr_ref in history['quays'] and "point" in history['quays'][ nsr_ref ]
								and history['quays'][ nsr_ref ]['point'] != [quay['lon'], quay['lat']]):
							nsr_relocate = True
							stops_history += 1

					# Check tags

					check_tags = ["name", "official_name", "ref", "unsigned_ref", "route_ref"]
					if ptv1 and osm_stop['id'] not in osm_ptv2_members:
						check_tags += ["public_transport", "bus"]

					if different_tags(quay, tags, check_tags):
						tag_modify = True

					# Modify if tag difference or if relocated in NSR or if last edit is by user in whitelist, else include for information

					if relocate or tag_modify:
						if nsr_relocate or relocate and (osm_stop['user'] in user_whitelist or tag_modify):
							produce_stop ("relocate", "quay", nsr_ref, osm_stop, quay, distance)
							stops_modify += 1
						elif tag_modify:
							produce_stop ("modify", "quay", nsr_ref, osm_stop, quay, distance)
							stops_modify += 1					
						else:
							produce_stop ("user edit", "quay", nsr_ref, osm_stop, quay, distance)
							if distance > 0:
								produce_stop ("nsr reference", "quay", nsr_ref, None, quay, 0)  # Output NSR stop for reference only
							stops_edit += 1					

					del quays[ nsr_ref ]

				else:
					produce_stop ("delete", "quay", nsr_ref, osm_stop, None, 0)
					stops_delete += 1

			# Include other stops witch do not have NSR ref tags

			else:
				if "highway" in tags and tags['highway'] == "bus_stop" or "amenity" in tags and tags['amenity'] == "bus_station":
					produce_stop ("other stop", None, None, osm_stop, None, 0)
					stops_other += 1

	#  Count NSR stations and quays which were not found in OSM. Output later
	
	for nsr_ref, station in iter(stations.items()):
		if station['municipality'][0:2] == county_id:
#			produce_stop ("new", "station", nsr_ref, None, station, 0)
			stops_new += 1
			stops_nsr += 1

	for nsr_ref, quay in iter(quays.items()):
		if quay['municipality'][0:2] == county_id and nsr_ref not in quays_abroad:  # Omit quays outside of Norway border
#			produce_stop ("new", "quay", nsr_ref, None, quay, 0)
			stops_new += 1
			stops_nsr += 1

	# Display summary information

	message ("\n")
	message ("  Stops in OSM           : %i\n" % stops_osm)
	message ("  Stops in NSR           : %i\n" % stops_nsr)
	message ("  User edited stops      : %i\n" % stops_edit)
	message ("  Other non-NSR stops    : %i\n" % stops_other)
	message ("  Modified stops         : %i\n" % stops_modify)
	message ("  Deleted stops          : %i\n" % stops_delete)
	message ("  New stops (preliminary): %i\n" % stops_new)     # Preliminary count; conclusion later
	message ("  Stops relocated in NSR : %i\n" % stops_history)

	stops_total_modify += stops_modify
	stops_total_delete += stops_delete
	stops_total_edits += stops_edit
	stops_total_others += stops_other

	# Produce output to file, including parent and child elements

	for element in osm_data['elements']:
		generate_osm_element (element)



# Output remaining NSR stations and quays which were not found in OSM

def process_new_stops():

	global stops_total_new, osm_data

	log ("\n\n*** NEW STOPS: Norway\n")

	osm_data = { 'elements': [] }

	for nsr_ref, station in iter(stations.items()):
		if station['municipality'][0:2] not in exclude_counties:
			produce_stop ("new", "station", nsr_ref, None, station, 0)
			stops_total_new += 1

	for nsr_ref, quay in iter(quays.items()):
		if quay['municipality'][0:2] not in exclude_counties and nsr_ref not in quays_abroad:  # Omit quays outside of Norway border
			produce_stop ("new", "quay", nsr_ref, None, quay, 0)
			stops_total_new += 1

	message ("\n\nNew stops in Norway: %i\n" % stops_total_new)

	for element in osm_data['elements']:
		generate_osm_element (element)



# Load NSR routes to discover which bus stops are being used.
# The set route_quays will contain all quays which are used by one or more routes.

def load_nsr_routes():

	url = "https://storage.googleapis.com/marduk-production/outbound/gtfs/rb_norway-aggregated-gtfs-basic.zip"
	in_file = urllib.request.urlopen(url)
	zip_file = zipfile.ZipFile(BytesIO(in_file.read()))

	# Load routes to discover quays in use from time table data

	file = zip_file.open("stop_times.txt")
	file_csv = csv.DictReader(TextIOWrapper(file, "utf-8"), fieldnames=['trip_id','stop_id'], delimiter=",")
	next(file_csv)

	for row in file_csv:
		quay_id = row['stop_id'][9:]
		route_quays.add(quay_id)

	file.close()
	in_file.close()



# Load date of last route assignment for all quays

def load_history():

	global history

	file_path = os.path.expanduser(history_filename)
	if os.path.isfile(file_path):
		file = open(file_path)
		history = json.load(file)
		file.close()
		message ("Loaded quay history\n")
	else:
		message ("Quay history '%s' not found\n" % file_path)



# Save date of last route assignment for all quays + all locations.
# Part 1 of this function needs to be executed before merging with OSM (to get all stations/quays).
# When merging, the old history dict will be used.

def save_history(save_file):

	global new_history

	if not save_file:
		# Part 1: Update all stations and quays with the current NSR location + today's date for quays with an active route

		new_history = copy.deepcopy(history)

		for ref, station in iter(stations.items()):
			if ref not in history['stations']:
				new_history['stations'][ ref ] = {}
			new_history['stations'][ ref ]['point'] = ( station['lon'], station['lat'] )

		for ref, quay in iter(quays.items()):
			if ref not in new_history['quays']:
				new_history['quays'][ ref ] = {}
			new_history['quays'][ ref ]['point'] = ( quay['lon'], quay['lat'] )

		for ref in route_quays:
			if ref not in new_history['quays']:
				new_history['quays'][ ref ] = {}
			new_history['quays'][ ref ]['date'] = today

	else:
		# Part 2: Save history file

		file_path = os.path.expanduser(history_filename)
		file = open(file_path, "w")
		json.dump(new_history, file, indent=1)
		file.close()
		message ("Saved quay history to '%s'\n" % history_filename)



# Read all NSR data into memory from Entur NeTEx file and convert to OSM tags
# The stations and quay dicts will contain all bus stations and bus stops, respectively

def load_nsr_data():

	url = "https://storage.googleapis.com/marduk-production/tiamat/Current_latest.zip"

	in_file = urllib.request.urlopen(url)
	zip_file = zipfile.ZipFile(BytesIO(in_file.read()))
	filename = zip_file.namelist()[0]
	file = zip_file.open(filename)

	tree = ET.parse(file)
	file.close()
	root = tree.getroot()

	ns_url = 'http://www.netex.org.uk/netex'
	ns = {'ns0': ns_url}  # Namespace

	stop_data = root.find("ns0:dataObjects/ns0:SiteFrame/ns0:stopPlaces", ns)

	station_count = 0
	quay_count = 0
	keep_one_year_count = 0
	exclude_one_year_count = 0

	# Iterate all stops

	for stop_place in stop_data.iter('{%s}StopPlace' % ns_url):

		stop_type = stop_place.find('ns0:StopPlaceType', ns)
		if stop_type != None:
			stop_type = stop_type.text
		else:
			stop_type = ""

		municipality = stop_place.find('ns0:TopographicPlaceRef', ns)
		if municipality != None:
			municipality = municipality.get('ref')
			if municipality[0:3] == "KVE":
				municipality = municipality.replace("KVE:TopographicPlace:", "")
			else:
				municipality = ""
		else:
			municipality = ""

		# Only keep bus stops in Norway

		if stop_type in ["busStation", "onstreetBus"] and municipality:

			name = stop_place.find('ns0:Name', ns)
			if name != None:
				name = name.text
			else:
				name = ""
			name = name.replace("  ", " ").strip()

			transport_mode = stop_place.find('ns0:TransportMode', ns)
			if transport_mode != None:
				transport_mode = transport_mode.text
			else:
				transport_mode = ""

			if transport_mode:
				transport_submode = stop_place.find('ns0:%sSubmode' % transport_mode.title(), ns)
				if transport_submode != None:
					transport_submode = transport_submode.text
				else:
					transport_submode = ""
			else:
				transport_submode = ""

			# Only keep stops which are not temporary

			if transport_submode != "railReplacementBus":

				# Get comments in NSR if any (for information to mapper only)

				note = ""
				key_list = stop_place.find('ns0:keyList', ns)

				if key_list != None:
					for key in key_list.iter('{%s}KeyValue' % ns_url):
						key_name = key.find('ns0:Key', ns).text
						key_value = key.find('ns0:Value', ns).text
						if key_name:
							if key_name.find("name") > 0:
								note += ";[" + key_value + "]"
							elif key_name.find("comment") > 0:
								if key_value:
									note += " " + key_value.replace("&lt;", "<")

				note = note.lstrip(";")

				# Get bus station

				if stop_type == "busStation":

					station_count  += 1

					location = stop_place.find('ns0:Centroid/ns0:Location', ns)
					longitude = float(location.find('ns0:Longitude', ns).text)
					latitude = float(location.find('ns0:Latitude', ns).text)

					nsr_ref = stop_place.get('id').replace("NSR:StopPlace:", "")

					entry = {
						'name': name,
						'lon': longitude,
						'lat': latitude,
						'municipality': municipality,
						'version': stop_place.get('version'),
					}

					if transport_submode:
						entry['submode'] = transport_submode
					if note:
						entry['nsrnote'] = note

					stations[ nsr_ref ] = entry

				# Avoid single quays for bus stations

				quay_data = stop_place.find('ns0:quays', ns)

				if quay_data != None and stop_type == "busStation":
					count = 0
					for quay in quay_data.iter('{%s}Quay' % ns_url):
						count += 1
					if count == 1:
						quay_data = None

				# Get quay nodes

				if quay_data != None:
					for quay in quay_data.iter('{%s}Quay' % ns_url):

						quay_count -= 1

						location = quay.find('ns0:Centroid/ns0:Location', ns)
						longitude = float(location.find('ns0:Longitude', ns).text)
						latitude = float(location.find('ns0:Latitude', ns).text)

						public_code = quay.find('ns0:PublicCode', ns)
						if public_code != None:
							ref = public_code.text
						else:
							ref = ""

						# Use quay reference for bus stations + add station name in official_name
						# Else use stop name if not station
						# Add public reference number/letter, if any, in parenteces in name (it is displayed on the quay)

						entry = {
							'lon': longitude,
							'lat': latitude,
							'municipality': municipality,
							'stoptype': stop_type,
							'version': quay.get('version')
						}

						if stop_type == "busStation":
							if ref:
								entry['name'] = ref
								entry['official_name'] = name + " (" + ref + ")"
								entry['ref'] = ref
							else:
								entry['official_name'] = name
								private_code = quay.find('ns0:PrivateCode', ns)
								if private_code != None:
									ref = private_code.text
									if ref:
										entry['unsigned_ref'] = ref
						else:
							if ref:
								entry['name'] = name + " (" + ref + ")"
								entry['ref'] = ref
							else:
								entry['name'] = name

							if transport_submode:
								entry['submode'] = transport_submode
							if note:
								entry['nsrnote'] = note

						nsr_ref = quay.get('id').replace("NSR:Quay:", "")

						# Omit quays which have not had a route last year, unless they belong to a bus station

						if (stop_type == "busStation"
								or nsr_ref in route_quays
								or nsr_ref in history['quays']
									and "date" in history['quays'][ nsr_ref ]
									and (datetime.date.today() - datetime.date.fromisoformat(history['quays'][ nsr_ref ]['date'])).days < 365):
							quays[ nsr_ref ] = entry

						if (stop_type != "busStation"
								and nsr_ref not in route_quays
								and nsr_ref in history['quays']
								and "date" in history['quays'][ nsr_ref ]):
							if (datetime.date.today() - datetime.date.fromisoformat(history['quays'][ nsr_ref ]['date'])).days >= 365:
#								message ("\tExcluded quay %s\n" % nsr_ref)
								exclude_one_year_count += 1
							else:
								keep_one_year_count += 1

	message ("%i kept up to one year, %i excluded after one year\n" % (keep_one_year_count, exclude_one_year_count))



# Upload changeset to OSM

def upload_changeset():

	if upload and stops_total_changes > 0:

		if stops_total_changes < 9900:  # Maximum upload is 10.000 elements
			
			today_date = time.strftime("%Y-%m-%d", time.localtime())

			changeset_root = ET.Element("osm")
			changeset_element = ET.Element("changeset")
			changeset_element.append(ET.Element("tag", k="comment", v="Bus stop import update for Norway"))
			changeset_element.append(ET.Element("tag", k="source", v="Entur: Norsk Stoppestedsregister (NSR)"))			
			changeset_element.append(ET.Element("tag", k="source:date", v=today_date))
			changeset_root.append(changeset_element)
			changeset_xml = ET.tostring(changeset_root, encoding='utf-8', method='xml')

			request = urllib.request.Request(osm_api + "changeset/create", data=changeset_xml, headers=osm_request_header, method="PUT")
			file = open_url(request)  # Create changeset
			changeset_id = file.read().decode()
			file.close()	

			message ("\nUploading %i elements to OSM in changeset #%s..." % (stops_total_changes, changeset_id))

			for element in upload_root:
				element[0].set("changeset", changeset_id)
				for tag in element[0].findall("tag"):
					if tag.attrib['k'] in manual_keys:  # Remove import keys
						element[0].remove(tag)

			indent_tree(upload_root)
			changeset_xml = ET.tostring(upload_root, encoding='utf-8', method='xml')

			request = urllib.request.Request(osm_api + "changeset/%s/upload" % changeset_id, data=changeset_xml, headers=osm_request_header)
			file = open_url(request)  # Post changeset in one go
			file.close()

			request = urllib.request.Request(osm_api + "changeset/%s/close" % changeset_id, headers=osm_request_header, method="PUT")
			file = open_url(request)  # Close changeset
			file.close()

			if debug:
				file_out = open("nsr_changeset.xml", "w")
				file_out.write(changeset_xml.decode())
				file_out.close()

			message ("\nDone\n\n")

		else:
			message ("\n\nCHANGESET TOO LARGE (%i) - UPLOAD MANUALLY WITH JOSM\n\n" % stops_total_changes)



# Insert line feeds into XLM file.

def indent_tree(elem, level=0):

	i = "\n" + level*"  "
	if len(elem):
		if not elem.text or not elem.text.strip():
			elem.text = i + "  "
		if not elem.tail or not elem.tail.strip():
			elem.tail = i
		for elem in elem:
			indent_tree(elem, level+1)
		if not elem.tail or not elem.tail.strip():
			elem.tail = i
	else:
		if level and (not elem.tail or not elem.tail.strip()):
			elem.tail = i


# Get authorization for later uploading to OSM.
# Returns request header for uploading.

def get_password():

	message ("This program will automatically upload bus stop changes to OSM\n")
	password = input ("Please enter OSM password for '%s' user: " % username)

	authorization = username.strip() + ":" + password.strip()
	authorization = "Basic " + base64.b64encode(authorization.encode()).decode()
	osm_request_header = request_header
	osm_request_header.update({'Authorization': authorization})

	request = urllib.request.Request(osm_api + "permissions", headers=osm_request_header)
	file = open_url(request)
	permissions = file.read().decode()
	file.close()

	if "allow_write_api" not in permissions:  # Authorized to modify the map
		sys.exit ("Wrong username/password or not authorized\n")

	return osm_request_header



# Main program

if __name__ == '__main__':

	# Init

	stations = {}
	quays = {}
	history = {}
	route_quays = set()
	osm_data = {}
	osm_way_nodes = []
	osm_relation_members = []
	osm_ptv2_members = []
	changeset_data = ""

	message ("\nnsr2osm v%s\n\n" % version)

	# Get password if automatic upload to OSM is selected

	if (len(sys.argv) == 2) and (sys.argv[1] == "-upload"):
		upload = True
	elif (len(sys.argv) == 2) and (sys.argv[1] == "-manual"):
		upload = False
	else:
		sys.exit ("Please choose eiter '-upload' or '-manual'")

	if upload:
		osm_request_header = get_password()

	# Load all stops from NSR

	start_time = time.time()
	today = datetime.date.today().isoformat()

	load_history()

	message ("Loading NSR routes... ")
	load_nsr_routes()
	message ("%i quays with routes\n" % len(route_quays))

	message ("Loading NSR bus stops/stations... ")
	load_nsr_data()
	message ("%i stations, %i quays\n" % (len(stations), len(quays)))

	save_history(save_file=False)

	# Load county id's and names from Kartverket api

	file = open_url("https://ws.geonorge.no/kommuneinfo/v1/fylker")
	county_data = json.load(file)
	file.close()

	counties = {}
	for county in county_data:
		counties[county['fylkesnummer']] = county['fylkesnavn'].strip()

	# Open output files

	if debug:
		log_file = open(out_filename + "_log.txt", "w")

	stops_total_modify = 0
	stops_total_delete = 0
	stops_total_new = 0
	stops_total_edits = 0
	stops_total_others = 0
	node_id = -1000

	osm_root = ET.Element("osm", version="0.6", generator="nsr2osm v%s" % version, upload="false")
	upload_root = ET.Element("osmChange", version="0.6", generator="nsr2osm")

	# Iterate counties to match NSR vs OSM and output result

	for county_id, county_name in sorted(counties.items()):

		if county_id not in exclude_counties:
			process_county (county_id, county_name)

	# Output remaining NSR stations and quays which were not found in OSM

	process_new_stops()  # This function resets osm_data dict

	# Close files

	osm_tree = ET.ElementTree(osm_root)
	indent_tree(osm_root)
	osm_tree.write(out_filename + ".osm", encoding="utf-8", method="xml", xml_declaration=True)

	if debug:
		log_file.close()

	stops_total_changes = stops_total_modify + stops_total_delete + stops_total_new

	message ("\n")
	message ("Bus stops/stations saved to OSM file '%s.osm' and log to file '%s_log.txt...'\n" % (out_filename, out_filename))
	message ("  Sum changes to OSM    : %i\n" % stops_total_changes)
	message ("    Sum modified        : %i\n" % stops_total_modify)
	message ("    Sum deleted         : %i\n" % stops_total_delete)
	message ("    Sum new             : %i\n" % stops_total_new)
	message ("  Sum user edits in OSM : %i\n" % stops_total_edits)
	message ("  Sum other stops in OSM: %i\n" % stops_total_others)
	message ("  Run time:             : %i seconds\n\n" % (time.time() - start_time))

	# Upload to OSM

	if upload and stops_total_changes > 0:
		confirm = input ("Please confirm upload of %i stop/station changes to OSM (y/n): " % stops_total_changes)
		if confirm.lower() == "y":
			upload_changeset()
			save_history(save_file=True)
		else:
			message ("Not uploaded\n")

	else:
		confirm = input ("Please confirm updating stop/station history file (y/n): ")
		if confirm.lower() == "y":
			save_history(save_file=True)
		else:
			message ("Not updated\n")
			
	message ("\n")
