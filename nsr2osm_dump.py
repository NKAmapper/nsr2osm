#!/usr/bin/env python3
# -*- coding: utf8

# nsr2osm_dump
# Converts public transportation stops from Entur NeTEx and GTFS files to OSM format
# Usage: stop2osm [county] (or "Norge" to get the whole country)
# Creates OSM file with name "Stoppested_" + county (or Current for whole country)


import html
import sys
import zipfile
import csv
from urllib import request
from io import BytesIO, TextIOWrapper
from xml.etree import ElementTree


version = "1.0.0"

filenames = [
	'Current',  # All of Norway
	'03_Oslo',
	'11_Rogaland',
	'15_More og Romsdal',
	'18_Nordland',
	'30_Viken',
	'34_Innlandet',
	'38_Vestfold_Telemark',
	'42_Agder',
	'46_Vestland',
	'50_Trondelag',
	'54_Troms_Finnmark'
]

ns_url = 'http://www.netex.org.uk/netex'
ns = {'ns0': ns_url}  # Namespace



# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()



# Produce a tag for OSM file

def make_osm_line(key,value):
	if value:
		escaped_value = html.escape(value).strip()
		file_out.write ('    <tag k="%s" v="%s" />\n' % (key, escaped_value))



# Main program

if __name__ == '__main__':

	message ("\nnsr2osm_dump v%s\n" % version)

	# Get county name

	county = ""
	if len(sys.argv) > 1:
		query = sys.argv[1].lower().replace(u"Ø", "O").replace(u"ø", "o")
		if query.lower() in ["norge", "norway"]:
			query = "current"
		for filename in filenames:
			if filename.lower().find(query) >= 0:
				county = filename
				break

	if not(county):
		sys.exit("County not found")


	# Get GTFS route files from Entur to match stops with routes later
	# Load route names (lines)

	message ("Loading routes... ")

	url = "https://storage.googleapis.com/marduk-production/outbound/gtfs/rb_norway-aggregated-gtfs-basic.zip"
	in_file = request.urlopen(url)
	zip_file = zipfile.ZipFile(BytesIO(in_file.read()))

	file = zip_file.open("routes.txt")
	file_csv = csv.DictReader(TextIOWrapper(file, "utf-8"), \
					fieldnames=['agency_id','route_id','route_short_name','route_long_name'], delimiter=",")
	next(file_csv)
	
	routes = {}

	for row in file_csv:
		if row['route_id'] not in routes:
			name = row['route_long_name']
			ref = row['route_short_name']
			if ref == name[ :len(ref) ]:  # Remove ref if part of name
				name = name[ len(ref): ].strip()
			if len(ref) > len(name) and name:  # Bug in source: Short/long name swapped for Trøndelag
				name, ref = ref, name
			routes[ row['route_id'] ] = {
				'ref': ref,
				'name': name,
				'agency': row['agency_id'][:3]
			}

	file.close()


	# Load trip to route translation (service journeys)

	file = zip_file.open("trips.txt")
	file_csv = csv.DictReader(TextIOWrapper(file, "utf-8"), \
					fieldnames=['route_id','trip_id','service_id','trip_headsign','direction_id'], delimiter=",")
	next(file_csv)
	
	trips = {}

	for row in file_csv:
		if row['trip_id'] not in trips:
			if row['direction_id'] == "0":
				direction = "ut"  # outbound
			else:
				direction = "inn"  # inbound (value 1)
			trips[ row['trip_id'] ] = {
				'route': row['route_id'],
				'direction': direction
			}

	file.close()


	# Load routes to discover quays in use from time table data

	file = zip_file.open("stop_times.txt")
	file_csv = csv.DictReader(TextIOWrapper(file, "utf-8"), fieldnames=['trip_id','stop_id'], delimiter=",")
	next(file_csv)
	
	route_quays = {}

	for row in file_csv:
		quay_id = row['stop_id'][9:]
		if quay_id not in route_quays:
			route_quays[quay_id] = []
		route = routes[ trips[ row['trip_id'] ]['route'] ]
		route_name = "[%s %s %s] %s" % (route['agency'], route['ref'], trips[ row['trip_id']]['direction'], route['name'])
		route_name = route_name.replace("  ", "")
		if route_name not in route_quays[quay_id]:
			route_quays[quay_id].append(route_name)

	file.close()
	in_file.close()

	message ("%s quays with routes\n" % len(route_quays))


	# Load NeTEx stops/quays from Entur

	message ("Loading NSR stops/quays... ")

	url = "https://storage.googleapis.com/marduk-production/tiamat/%s_latest.zip" % county.replace(" ", "%20")

	in_file = request.urlopen(url)
	zip_file = zipfile.ZipFile(BytesIO(in_file.read()))
	filename = zip_file.namelist()[0]
	file = zip_file.open(filename)

	tree = ElementTree.parse(file)
	file.close()
	root = tree.getroot()

	stop_places = root.find("ns0:dataObjects/ns0:SiteFrame/ns0:stopPlaces", ns)


	# Open output file and produce OSM file header

	message ("\nGenerating OSM file... ")

	filename = county
	if county[0] in ['0', '1', '2', '5']:
		filename = county[3:]
	filename = "nsr_" + filename.lower().replace(" ", "_") + ".osm"

	file_out = open(filename, "w")

	file_out.write ('<?xml version="1.0" encoding="UTF-8"?>\n')
	file_out.write ('<osm version="0.6" generator="nsr2osm v%s">\n' % version)

	node_id = -1000

	# Iterate all stops

	for stop_place in stop_places.iter('{%s}StopPlace' % ns_url):

		municipality = stop_place.find('ns0:TopographicPlaceRef', ns)
		if municipality != None:
			municipality = municipality.get('ref')
			if municipality[0:3] != "KVE":
				continue  # Skip stops abroad
		else:
			continue  # Skip stops abroad

		municipality = municipality.replace("KVE:TopographicPlace:", "")

		# Get stop type

		stop_type = stop_place.find('ns0:StopPlaceType', ns)
		if stop_type != None:
			stop_type = stop_type.text
		else:
			stop_type = ""

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

		# Get name

		name = stop_place.find('ns0:Name', ns)
		if name != None:
			name = name.text
		else:
			name = ""
		name = name.replace("  ", " ").strip()
		full_name = ""

		if stop_type == "railStation":
			if "stasjon" in name:
				full_name = name
				name = name.replace(" stasjon", "").strip()

		elif stop_type in ["ferryStop", "harbourPort"]:
			for avoid_name in [" kai", u" båtkai", " ferjekai", " fergekai", " fergeleie", " ferjeleie", u" hurtigbåtkai", " hurtigrutekai"]:
				if avoid_name in name:
					full_name = name
					name = name.replace(avoid_name, "").strip()
					break
				elif avoid_name.title() in name:
					full_name = name
					name = name.replace(avoid_name.title(), "").strip()
					break

		# Get any sami or kven names

		languages = {}
		alt_names = stop_place.find('ns0:alternativeNames', ns)
		if alt_names != None:
			norwegian_name = name
			for alt_name in alt_names.iter('{%s}AlternativeName' % ns_url):
				language_name = alt_name.find('ns0:Name', ns)
				language = language_name.attrib['lang']
				if language in ['sme', 'sma', 'smj', 'sms', 'fkv']:
					language = language.replace("sme", "se")
					languages[language] = language_name.text
					name = languages[language] + " / " + name

		# Get wheelchair status

		wheelchair = ""
		accessibility = stop_place.find('ns0:AccessibilityAssessment', ns)
		if accessibility != None:
			wheelchair = accessibility.find('ns0:limitations/ns0:AccessibilityLimitation/ns0:WheelchairAccess', ns).text
			if wheelchair == "unknown":
				wheelchair = ""
			elif wheelchair == "true":
				wheelchair = "yes"
			elif wheelchair == "partial":
				wheelchair = "limited"
			elif wheelchair == "false":
				wheelchair = "no"

		# Get toilet and bench status

		toilet = False
#		waiting_room = False

		equipment = stop_place.find('ns0:placeEquipments', ns)
		if equipment != None:
			if equipment.find('ns0:SanitaryEquipment', ns) != None:
				toilet = True
#			if eqipment.find('ns0:WaitingRoomEquipment', ns):  # Not used
#				waiting_room = True

		# Get comments, if any

		note = ""
		new_note = ""
		tag = ""
		key_list = stop_place.find('ns0:keyList', ns)

		if key_list != None:
			for key in key_list.iter('{%s}KeyValue' % ns_url):
				key_name = key.find('ns0:Key', ns).text
				key_value = key.find('ns0:Value', ns).text
				if key_name:
					if tag != key_name[0:6]:
						if new_note:
							note += ";" + new_note
							new_note = ""
						tag = key_name[0:6]

					if "name" in key_name:
						new_note += "[" + key_value + "]"
					elif "comment" in key_name:
						if key_value:
							new_note += " " + key_value.replace("&lt;", "<")
					elif "removed" in key_name:
						new_note = ""

		if new_note:
			note += ";" + new_note
		note = note.lstrip(";")


		# Produce station node

		if stop_type in ["busStation", "railStation"]:

			node_id -= 1

			location = stop_place.find('ns0:Centroid/ns0:Location', ns)
			longitude = location.find('ns0:Longitude', ns).text
			latitude = location.find('ns0:Latitude', ns).text

			file_out.write ('  <node id="%i" lat="%s" lon="%s">\n' % (node_id, latitude, longitude))

			if stop_type == "busStation":
				make_osm_line ("amenity", "bus_station")			
			elif stop_type == "railStation":
				make_osm_line ("railway", "station")
				make_osm_line ("train", "yes")

			make_osm_line ("ref:nsrs", stop_place.get('id').replace("NSR:StopPlace:", ""))
			make_osm_line ("name", name)

			if languages:
				make_osm_line ("name:no", norwegian_name)
				for language, language_name in iter(languages.items()):
					make_osm_line ("name:%s" % language, language_name)

			if full_name:
				if languages:
					make_osm_line ("official_name:no", full_name)
				else:
					make_osm_line ("official_name", full_name)

			if wheelchair:
				make_osm_line ("wheelchair", wheelchair)

			if toilet:
				make_osm_line ("toilets", "yes")

			make_osm_line ("MUNICIPALITY", municipality)
			make_osm_line ("STOPTYPE", stop_type)
			make_osm_line ("SUBMODE", transport_submode)
			make_osm_line ("VERSION", stop_place.get('version'))
			make_osm_line ("NSRNOTE", note)

			quays = stop_place.find('ns0:quays', ns)
			count = 0
			if quays != None:
				for quay in quays.iter('{%s}Quay' % ns_url):
					count += 1

			make_osm_line ("QUAYS", str(count))

			file_out.write ('  </node>\n')


		# Produce quay nodes

		quays = stop_place.find('ns0:quays', ns)

		if quays != None:
			for quay in quays.iter('{%s}Quay' % ns_url):

				node_id -= 1

				location = quay.find('ns0:Centroid/ns0:Location', ns)
				longitude = location.find('ns0:Longitude', ns).text
				latitude = location.find('ns0:Latitude', ns).text

				file_out.write ('  <node id="%i" lat="%s" lon="%s">\n' % (node_id, latitude, longitude))

				if stop_type == "onstreetBus":
					make_osm_line ("highway", "bus_stop")
				elif stop_type == "busStation":
					make_osm_line ("highway", "bus_stop")
				elif stop_type == "onstreetTram":
					make_osm_line ("railway", "tram_stop")
					make_osm_line ("tram", "yes")
				elif stop_type == "metroStation":
					make_osm_line ("railway", "stop")
					make_osm_line ("subway", "yes")
				elif stop_type == "ferryStop":
					make_osm_line ("amenity", "ferry_terminal")
					make_osm_line ("foot", "yes")
				elif stop_type == "harbourPort":
					make_osm_line ("amenity", "ferry_terminal")
					make_osm_line ("motor_vehicle", "yes")
					make_osm_line ("foot", "yes")
				elif stop_type == "railStation":
					make_osm_line ("railway", "stop")
					make_osm_line ("train", "yes")
				elif stop_type == "airport":
					if transport_submode == "helicopterService":
						make_osm_line ("aeroway", "heliport")
					else:
						make_osm_line ("aeroway", "aerodrome")

				public_code = quay.find('ns0:PublicCode', ns)
				if public_code != None:
					ref = public_code.text
				else:
					ref = ""

				# Add public reference number/letter, if any, in parenteces in name (it is displayed on the quay)

				if ref:
					make_osm_line ("name", name + " (" + ref + ")")
					make_osm_line ("ref", ref)
				else:
					make_osm_line ("name", name)
					private_code = quay.find('ns0:PrivateCode', ns)
					if private_code != None:
						ref = private_code.text
						if ref and ref.strip():
							make_osm_line ("unsigned_ref", ref)

				if languages:
					make_osm_line ("name:no", norwegian_name)
					for language, language_name in iter(languages.items()):
						make_osm_line ("name:%s" % language, language_name)

				if full_name:
					if languages:
						make_osm_line ("official_name:no", full_name)
					else:
						make_osm_line ("official_name", full_name)

				# Shelters and monitors

				equipment = quay.find('ns0:placeEquipments', ns)
				if equipment != None:
					shelter = equipment.find('ns0:ShelterEquipment', ns)
					if shelter != None:
						shelter = shelter.find('ns0:Enclosed', ns).text
						if shelter == "true":
							make_osm_line ("shelter", "yes")

					for sign in equipment.iter('{%s}GeneralSign' % ns_url):
						sign_content = sign.find('ns0:Content', ns)
						if sign_content != None:
							sign_content = sign_content.text
							if sign_content == "RealtimeMonitor":
								make_osm_line ("passenger_information_display", "yes")

#						sign_code = sign.find('ns0:PrivateCode', ns)
#						if sign_code != None:
#							sign_code = sign_code.text
#							if sign_content == "512":
#								make_osm_line ("traffic_sign", "NO:512")

				# Wheelchair status

				accessibility = quay.find('ns0:AccessibilityAssessment', ns)
				if accessibility != None:
					wheelchair = accessibility.find('ns0:limitations/ns0:AccessibilityLimitation/ns0:WheelchairAccess', ns).text
					if wheelchair == "true":
						make_osm_line ("wheelchair", "yes")
					elif wheelchair == "partial":
						make_osm_line ("wheelchair", "limited")
					elif wheelchair == "false":
						make_osm_line ("wheelchair", "no")

				elif wheelchair:  # Use StopPlace tag
					make_osm_line ("wheelchair", wheelchair)

				# Other tags

				quay_id = quay.get('id').replace("NSR:Quay:", "")
				make_osm_line ("ref:nsrq", quay_id)
				make_osm_line ("MUNICIPALITY", municipality)
				make_osm_line ("STOPTYPE", stop_type)
				make_osm_line ("SUBMODE", transport_submode)
				make_osm_line ("VERSION", quay.get('version'))
				make_osm_line ("NSRNOTE", note)

				if quay_id in route_quays:
					make_osm_line("ROUTE", ";".join(sorted(route_quays[quay_id])))

				file_out.write ('  </node>\n')


	# Produce OSM file footer

	file_out.write ('</osm>\n')
	file_out.close()

	message ("\n%i stops/quays saved to file '%s'\n\n" % ((-node_id - 1000), filename))
