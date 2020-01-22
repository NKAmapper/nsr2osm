#!/usr/bin/env python
# -*- coding: utf8

# nsr2osm_dump
# Converts public transportation stops from Entur NeTex files to OSM format
# Usage: stop2osm [county] (or "Norge" to get the whole country)
# Creates OSM file with name "Stoppested_" + county (or Current for whole country)


import cgi
import sys
import urllib2
import zipfile
import StringIO
from xml.etree import ElementTree


version = "0.8.0"

filenames = [
	'Current',  # All of Norway
	'03_Oslo',
	'11_Rogaland',
	'15_More og Romsdal',
	'18_Nordland',
	'30_Viken',
	'34_Innlandet',
	'38_Vestfold og Telemark',
	'42_Agder',
	'46_Vestland',
	'50_Trondelag',
	'54_Troms og Finnmark'
]


# Produce a tag for OSM file

def make_osm_line(key,value):
    if value:
		encoded_value = cgi.escape(value.encode('utf-8'),True).strip()
		file_out.write ('    <tag k="%s" v="%s" />\n' % (key, encoded_value))



# Main program

if __name__ == '__main__':

	# Get county name

	county = ""
	if len(sys.argv) > 1:
		query = sys.argv[1].decode("utf-8").lower().replace(u"Ø", "O").replace(u"ø", "o")
		if query.lower() in ["norge", "norway"]:
			query = "current"
		for filename in filenames:
			if filename.lower().find(query) >= 0:
				county = filename
				break

	if not(county):
		sys.exit("County not found")

	# Read all data into memory

	url = "https://storage.googleapis.com/marduk-production/tiamat/%s_latest.zip" % county.replace(" ", "%20")

	in_file = urllib2.urlopen(url)
	zip_file = zipfile.ZipFile(StringIO.StringIO(in_file.read()))
	filename = zip_file.namelist()[0]
	file = zip_file.open(filename)

	tree = ElementTree.parse(file)
	file.close()
	root = tree.getroot()

	ns_url = 'http://www.netex.org.uk/netex'
	ns = {'ns0': ns_url}  # Namespace

	stop_places = root.find("ns0:dataObjects/ns0:SiteFrame/ns0:stopPlaces", ns)

	# Open output file and produce OSM file header

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

		# Get comments if any

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
				for language, language_name in languages.iteritems():
					make_osm_line ("name:%s" % language, language_name)

			if full_name:
				if languages:
					make_osm_line ("official_name:no", full_name)
				else:
					make_osm_line ("official_name", full_name)

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
					for language, language_name in languages.iteritems():
						make_osm_line ("name:%s" % language, language_name)

				if full_name:
					if languages:
						make_osm_line ("official_name:no", full_name)
					else:
						make_osm_line ("official_name", full_name)

				make_osm_line ("ref:nsrq", quay.get('id').replace("NSR:Quay:", ""))
				make_osm_line ("MUNICIPALITY", municipality)
				make_osm_line ("STOPTYPE", stop_type)
				make_osm_line ("SUBMODE", transport_submode)
				make_osm_line ("VERSION", quay.get('version'))
				make_osm_line ("NSRNOTE", note)

				file_out.write ('  </node>\n')


	# Produce OSM file footer

	file_out.write ('</osm>\n')
	file_out.close()
