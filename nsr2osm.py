#!/usr/bin/env python
# -*- coding: utf8

# nsr2osm
# Converts public transportation stops from Entur NeTex files and matches with OSM for update in JOSM
# Reads NSR data from Entur NeTEx file (XML)
# Usage: stop2osm.py
# Creates OSM file with name "nsr_update.osm" and log file "nsr_update_log.txt"


import cgi
import sys
import json
import urllib
import urllib2
import zipfile
import StringIO
import math
import copy
import time
from xml.etree import ElementTree


version = "0.5.0"

request_header = {"User-Agent": "nsr2osm/" + version}

exclude_counties = ["50", "19"]  # Omit Trøndelag and Troms for now

user_whitelist = ["nsr2osm", "ENTUR Johan Wiklund", "ENTUR Fredrik Edler", "Wulfmorn"]  # Only modify stops in OSM if last edit is from these users

quays_abroad = ["101150", "15343"]  # Quays just outside of Norway border (to avoid duplicates)

out_filename = "nsr_update"

max_distance = 1.0  # Nodes relocated more than or equal to this distance will get new coordinates (meters)

escape_characters = {
	'"': "&quot;",
	"'": "&apos;",
	"<": "&lt;",
	">": "&gt;"
}


# Open file/api, try up to 5 times, each time with double sleep time

def open_url (url):

	tries = 0
	while tries < 5:
		try:
			return urllib2.urlopen(url)
		except urllib2.HTTPError, e:
			if e.code in [429, 503, 504]:  # Too many requests, Service unavailable or Gateway timed out
				if tries  == 0:
					message ("\n") 
				message ("\rRetry %i... " % (tries + 1))
				time.sleep(5 * (2**tries))
				tries += 1
			elif e.code in [401, 403]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Unauthorized or Blocked
				sys.exit()
			elif e.code in [400, 409, 412]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Bad request, Conflict or Failed precondition
				message ("%s\n" % str(e.read()))
				sys.exit()
			else:
				raise
	
	message ("\nHTTP error %i: %s\n" % (e.code, e.reason))
	sys.exit()


# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()


# Log query results

def log(log_text):

	if type(log_text) == unicode:
		log_file.write(log_text.encode("utf-8"))
	else:
		log_file.write(log_text)


# Escape string for osm xml file

def escape (value):

	value = value.replace("&", "&amp;")
	for change, to in escape_characters.iteritems():
		value = value.replace(change, to)
	return value


# Generate one osm tag

def osm_tag (key, value):

	value = value.strip()
	if value:
		value = escape(value).encode('utf-8')
		key = escape(key).encode('utf-8')
		line = "    <tag k='%s' v='%s' />\n" % (key, value)
		file_out.write (line)


# Generate one osm line

def osm_line (value):

	value = value.encode('utf-8')
	file_out.write (value)


# Compute approximation of distance between two coordinates, in meters
# Works for short distances

def compute_distance (osm_stop, nsr_stop):

	if "lon" in osm_stop:
		lon1, lat1, lon2, lat2 = map(math.radians, [osm_stop['lon'], osm_stop['lat'], nsr_stop['lon'], nsr_stop['lat']])
		x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
		y = lat2 - lat1
		return round(6371000 * math.sqrt( x*x + y*y ), 1)  # One decimal

	else:
		return 0



# Generate OSM/XML for one OSM element
# Parameter:
# - element:	Dict of OSM element in same format as returned by Overpass API
#				Containes 'modify=True' if 'action=modify' should be included in output for the element

def generate_osm_element (element):

	if "modify" in element:
		action_text = "action='modify' "
	else:
		action_text = ""

	if element['id'] < 0:
		line = "  <node id='%i' %svisible='true' lat='%f' lon='%f'>\n" % (element['id'], action_text, element['lat'], element['lon'])
		osm_line (line)

	else:
		line = u"  <%s id='%i' %stimestamp='%s' uid='%i' user='%s' visible='true' version='%i' changeset='%i'"\
				% (element['type'], element['id'], action_text, element['timestamp'], element['uid'], escape(element['user']),\
				element['version'], element['changeset'])

		if element['type'] == "node":
			line_end = " lat='%f' lon='%f'>\n" % (element['lat'], element['lon'])
		else:
			line_end = ">\n"

		osm_line (line + line_end)

	if "nodes" in element:
		for node in element['nodes']:
			line = "    <nd ref='%i' />\n" % node
			osm_line (line)

	if "members" in element:
		for member in element['members']:
			line = "    <member type='%s' ref='%i' role='%s' />\n" % (escape(member['type']), member['ref'], member['role'])
			osm_line (line)

	if "tags" in element:
		for key, value in element['tags'].iteritems():
			osm_tag (key, value)

	line = "  </%s>\n" % element['type']
	osm_line (line)



# Output stop place
# Parameters:
# - action:		new/modify/delete/user edit/other stop/nsr reference
# - stop_type:	station/quay
# - nsr_ref:	Unique station or quay reference in NSR, or None
# - osm_stop:	Dict of OSM element from Overpass, or None
# - nsr_stop:	Dict of NSR station or quay generated from Entur input file, or None
# - distance:	Computed distance between coordinates for stop in NSR vs OSM, or None

def produce_stop (action, stop_type, nsr_ref, osm_stop, nsr_stop, distance):

	global node_id, osm_data, osm_ways

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
			'tags': {},
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
			entry['modify'] = True
			if stop_type == "station":
				entry['tags']['amenity'] = "bus_station"
			elif stop_type == "quay":
				entry['tags']['highway'] = "bus_stop"

		else:
			entry['tags']['NSR_REFERENCE'] = "yes"  # Mark element as reference only (not for update)

		osm_data['elements'].append(entry)

		log (json.dumps(nsr_stop, indent=2))
		log ("\n")

	# Modify stop

	elif action == "modify":

		# Detach stop if it is a node in a way

		if osm_stop['id'] in osm_ways:
			entry = copy.deepcopy(osm_stop)
			entry['modify'] = True
			del entry['tags']
			osm_data['elements'].append(entry)
			stops_new += 1

			node_id -= 1
			osm_stop['id'] = node_id
			log ("  Detach stop node from way\n")

		# Modify tags

		if osm_stop['type'] == "node":
			osm_stop['lat'] = nsr_stop['lat']
			osm_stop['lon'] = nsr_stop['lon']

		if stop_type == "station":
			osm_stop['tags']['amenity'] = "bus_station"
			osm_stop['tags']['ref:nsrs'] = nsr_ref
			if ("highway" in osm_stop['tags']) and (osm_stop['tags']['highway'] == "bus_stop"):
				del osm_stop['tags']['highway']
				log ("  Change tagging from 'highway = bus_stop' to 'amenity = bus_station'\n")
			check_keys = ['name']

		elif stop_type == "quay":
			osm_stop['tags']['highway'] = "bus_stop"
			osm_stop['tags']['ref:nsrq'] = nsr_ref
			if ("amenity" in osm_stop['tags']) and (osm_stop['tags']['amenity'] == "bus_station"):
				del osm_stop['tags']['amenity']
				log ("  Change tagging from 'amenity = bus_station' to 'highway = bus_stop'\n")
			check_keys = ["name",  "official_name", "ref", "unsigned_ref"]					

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

		osm_stop['modify'] = True

	# Mark stop as deleted (for manual deletion in JOSM)

	elif action == "delete":

		osm_stop['tags']['DELETE'] = "yes"
#		osm_stop['modify'] = True
		log (json.dumps(osm_stop, indent=2))
		log ("\n")

	# Mark stop as edited by user (for information only)

	elif action == "user edit":

		osm_stop['tags']['EDIT'] = osm_stop['timestamp'][0:10]
		osm_stop['tags']['USER'] = osm_stop['user']

		if distance > 0:
			osm_stop['tags']['DISTANCE'] = str(distance)  # Include distance from NSR coodinate if different

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

		log (json.dumps(osm_stop, indent=2))
		log ("\n")

	# Include bus_stop or bus_station which is not present in NSR (without ref:nsrs/nsrq tags)

	elif action == "other stop":

		osm_stop['tags']['OTHER'] = osm_stop['timestamp'][0:10]
		osm_stop['tags']['USER'] = osm_stop['user']		
		log (json.dumps(osm_stop, indent=2))
		log ("\n")



# Read stops from OSM for county, match with NSR and output result
# Paramters:
# - county_id:		Two digit county reference
# - county_name:	Full name of county

def process_county (county_id, county_name):

	global stops_total_changes, stops_total_edits, stops_total_others, osm_data, osm_ways

	message ("\nLoading #%s %s county... " % (county_id, county_name))
	log ("\n\n*** COUNTY: %s %s\n" % (county_id, county_name))

	# Read stop places from Overpass, plus any parent ways/relations and children

	query = '[out:json][timeout:60];(area["name"="%s"][admin_level=4];)->.a;(nwr["amenity"="bus_station"](area.a);nwr["highway"="bus_stop"](area.a););out center meta;' \
			% (county_name.encode("utf-8"))
#	query = '[out:json][timeout:60];(area["name"="%s"][admin_level=4];)->.a;(nwr["ref:nsrs"](area.a);nwr["ref:nsrq"](area.a););out center meta;' \
#			% (county_name.encode("utf-8"))
	request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
	file = open_url(request)
	osm_data = json.load(file)
	file.close()

	query = query.replace("out center meta", "<;out meta")
	request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
	file = open_url(request)
	osm_parents = json.load(file)
	file.close()

	query = query.replace("<;out meta", ">;out meta")
	request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
	file = open_url(request)
	osm_children = json.load(file)
	file.close()

	message ("\n  Overpass               : %i stops, %i parents, %i children\n" % (len(osm_data['elements']), len(osm_parents['elements']), len(osm_children['elements'])))

	# Make set of all stop nodes witch are part of ways

	osm_ways = []
	for element in osm_parents['elements']:
		if "nodes" in element:
			for node in element['nodes']:
				osm_ways.append(node)

	# Iterate stop places from OSM and discover differences between NSR and OSM
	# The dict osm_data will be modified to include all stop places to be output
	# When done, only NSR stop places which did not get a match remain in NSR stations/quays dicts

	stops_nsr = 0
	stops_osm = 0
	stops_modify = 0
	stops_delete = 0
	stops_new = 0
	stops_edit = 0
	stops_other = 0

	index = 0
	the_end = False
	end_element = osm_data['elements'][-1]  # Iteration will end at this stop place
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
					distance = compute_distance(osm_stop, station)
					modify = False

					if distance >= max_distance:
						modify = True

					else:
						osm_name = ""
						nsr_name = ""
						if "name" in station:
							nsr_name = station['name']
						if "name" in tags:
							osm_name = tags['name']

						if osm_name != nsr_name:
							modify = True

					# Only modify stop if import user has last edit in OSM, else include for information

					if modify:
						if osm_stop['user'] in user_whitelist:
							produce_stop ("modify", "station", nsr_ref, osm_stop, station, distance)
							stops_modify += 1
						else:
							produce_stop ("user edit", "station", nsr_ref, osm_stop, station, distance)
							if distance > 0:
								produce_stop ("nsr reference", "station", nsr_ref, None, station, 0)  # Output NSR stop for reference only
							stops_edit += 1

					del stations[nsr_ref]

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
					distance = compute_distance(osm_stop, quay)
					modify = False

					if distance >= max_distance:
						modify = True
					else:
						for tag in ["name", "official_name", "ref", "unsigned_ref"]:
							osm_tag = ""
							nsr_tag = ""
							if tag in quay:
								nsr_tag = quay[tag]
							if tag in tags:
								osm_tag = tags[tag]

							if osm_tag != nsr_tag:
								modify = True
								break

					# Only modify stop if import user has last edit in OSM, else include for information

					if modify:
						if osm_stop['user'] in user_whitelist:
							produce_stop ("modify", "quay", nsr_ref, osm_stop, quay, distance)
							stops_modify += 1						
						else:
							produce_stop ("user edit", "quay", nsr_ref, osm_stop, quay, distance)
							if distance > 0:
								produce_stop ("nsr reference", "quay", nsr_ref, None, quay, 0)  # Output NSR stop for reference only
							stops_edit += 1

					del quays[nsr_ref]

				else:
					produce_stop ("delete", "quay", nsr_ref, osm_stop, None, 0)
					stops_delete += 1

			# Include other stops witch do not have NSR ref tags

			else:
				if ("highway" in tags) and (tags['highway'] == "bus_stop"):
					stop_type = "quay"
				elif ("amenity" in tags) and (tags['amenity'] == "bus_station"):
					stop_type = "station"
				produce_stop ("other stop", stop_type, None, osm_stop, None, 0)
				stops_other += 1

	#  Count NSR stations and quays which were not found in OSM. Output later
	
	for nsr_ref, station in stations.iteritems():
		if station['municipality'][0:2] == county_id:
#			produce_stop ("new", "station", nsr_ref, None, station, 0)
			stops_new += 1
			stops_nsr += 1

	for nsr_ref, quay in quays.iteritems():
		if (quay['municipality'][0:2] == county_id) and (nsr_ref not in quays_abroad):  # Omit quays outside of Norway border
#			produce_stop ("new", "quay", nsr_ref, None, quay, 0)
			stops_new += 1
			stops_nsr += 1

	# Display summary information

	message ("  Stops in OSM           : %i\n" % stops_osm)
	message ("  Stops in NSR           : %i\n" % stops_nsr)
	message ("  Modified stops         : %i\n" % stops_modify)
	message ("  Deleted stops          : %i\n" % stops_delete)
	message ("  New stops (preliminary): %i\n" % stops_new)     # Preliminary count; conclusion later
	message ("  User edited stops      : %i\n" % stops_edit)
	message ("  Other non-NSR stops    : %i\n" % stops_other)

	stops_total_changes += stops_modify + stops_delete
	stops_total_edits += stops_edit
	stops_total_others += stops_other

	# Produce output to file, including parent and child elements

	for element in osm_data['elements']:
		generate_osm_element (element)

	for element in osm_parents['elements']:
		generate_osm_element (element)

	for element in osm_children['elements']:
		generate_osm_element (element)



# Output remaining NSR stations and quays which were not found in OSM
# Omit Trøndelag, Troms (county 50 and 19)

def process_new_stops():

	global stops_total_changes, osm_data, osm_ways

	log ("\n\n*** NEW STOPS: Norway\n")

	osm_data = { 'elements': [] }
	osm_ways = []

	stops_new = 0

	for nsr_ref, station in stations.iteritems():
		if station['municipality'][0:2] not in exclude_counties:
			produce_stop ("new", "station", nsr_ref, None, station, 0)
			stops_new += 1

	for nsr_ref, quay in quays.iteritems():
		if (quay['municipality'][0:2] not in exclude_counties) and (nsr_ref not in quays_abroad):  # Omit quays outside of Norway border
			produce_stop ("new", "quay", nsr_ref, None, quay, 0)
			stops_new += 1

	message ("\n\nNew stops in Norway: %i\n\n" % stops_new)

	stops_total_changes += stops_new

	for element in osm_data['elements']:
		generate_osm_element (element)



# Read all NSR data into memory from Entur NeTEx file and convert to OSM tags
# The stations and quay dicts will contain all bus stations and bus stops, respectively

def load_nsr_data():

	url = "https://storage.googleapis.com/marduk-production/tiamat/Current_latest.zip"

	in_file = urllib2.urlopen(url)
	zip_file = zipfile.ZipFile(StringIO.StringIO(in_file.read()))
	filename = zip_file.namelist()[0]
	file = zip_file.open(filename)

	tree = ElementTree.parse(file)
	file.close()
	root = tree.getroot()

	ns_url = 'http://www.netex.org.uk/netex'
	ns = {'ns0': ns_url}  # Namespace

	stop_data = root.find("ns0:dataObjects/ns0:SiteFrame/ns0:stopPlaces", ns)

	station_count = 0
	quay_count = 0

	# Iterate all stop places

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

		# Only keep bus stop places in Norway

		if (stop_type in ["busStation", "onstreetBus"]) and municipality:

			name = stop_place.find('ns0:Name', ns).text
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

			# Only keep stop places which are not temporary

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

					stations[nsr_ref] = entry

				# Avoid single quays for bus stations

				quay_data = stop_place.find('ns0:quays', ns)

				if (quay_data != None) and (stop_type == "busStation"):
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
						# Else use stop place name if not station
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

						quays[nsr_ref] = entry



# Main program

if __name__ == '__main__':

	# Load NSR data

	start_time = time.time()
	stations = {}
	quays = {}
	osm_data = {}
	osm_ways = []

	message ("\nNSR2OSM v%s\n" % version)
	message ("Loading NSR bus stop places... ")
	load_nsr_data()
	message ("%i stations, %i quays\n" % (len(stations), len(quays)))

	# Load county id's and names from Kartverket api

	file = open_url("https://ws.geonorge.no/kommuneinfo/v1/fylker")
	county_data = json.load(file)
	file.close()

	counties = {}
	for county in county_data:
		counties[county['fylkesnummer']] = county['fylkesnavn'].strip()

	# Open output files

	log_file = open(out_filename + "_log.txt", "w")
	stops_total_changes = 0
	stops_total_edits = 0
	stops_total_others = 0
	node_id = -1000

	file_out = open(out_filename + ".osm", "w")
	file_out.write ('<?xml version="1.0" encoding="UTF-8"?>\n')
	file_out.write ('<osm version="0.6" generator="nsr2osm v%s" upload="false">\n' % version)

	# Iterate counties to match NSR vs OSM and output result

	for county_id, county_name in sorted(counties.iteritems()):

		if county_id not in exclude_counties:
			process_county (county_id, county_name)

	# Output remaining NSR stations and quays which were not found in OSM

	process_new_stops()

	# Wrap up

	file_out.write ('</osm>\n')
	file_out.close()
	log_file.close()

	message ("\n")
	message ("Stop places saved to OSM file '%s.osm' and log to file '%s_log.txt...'\n" % (out_filename, out_filename))
	message ("  Sum changes to OSM    : %i\n" % stops_total_changes)
	message ("  Sum user edits in OSM : %i\n" % stops_total_edits)
	message ("  Sum other stops in OSM: %i\n" % stops_total_others)
	message ("  Run time              : %i seconds\n\n" % (time.time() - start_time))
	
