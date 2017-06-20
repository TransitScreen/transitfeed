import threading
from flask import Flask, request, url_for, send_file, redirect, session, render_template, make_response
from flask_session import Session
from flask.json import jsonify
from feedvalidator import RunValidationOutputToFilename, ParseCommandLineArguments
import urllib
import StringIO
import transitfeed
from transitfeed import util, schedule
from schedule_viewer import FindDefaultFileDir, StoppableHTTPServer, ScheduleRequestHandler
from gtfsscheduleviewer.marey_graph import MareyGraph
import bisect
import uuid
import sys
import traceback
import cPickle
import pickle
import json
import pprint
# from flask_cache import Cache
import shelve

app = Flask(__name__, static_url_path='/static')
app.config['DEBUG'] = False
# sess = Session()
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_THRESHOLD'] = 1000
app.config['SESSION_COOKIE_HTTPONLY'] = False
app.config['SECRET_KEY'] = '&u%d!!8.5jpZ*!_g'
# sess.init_app(app)
Session(app)

# cache = Cache(app,config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR':'cache', 'CACHE_DEFAULT_TIMEOUT':'600'})
# cache.init_app(app)

class Stop:
	def __init__(self, stop_name, stop_id, stop_lat, stop_lon, location_type):
		self.stop_name = stop_name
		self.stop_id = stop_id
		self.stop_lat = stop_lat
		self.stop_lon = stop_lon
		self.location_type = location_type

class Trip:
	def __init__(self, block_id, route_id, service_id, shape_id, trip_headsign,trip_id):
		self.block_id = block_id
		self.route_id = route_id
		self.service_id = service_id
		self.trip_headsign = trip_headsign
		self.trip_id = trip_id

class Route:
	def __init__(self, route_long_name, route_id, route_short_name, route_type):
		self.route_long_name = route_long_name
		self.route_id = route_id
		self.route_short_name = route_short_name
		self.route_type = route_type

class Agency:
	def __init__(self, agency_name):
		self.agency_name = agency_name

@app.route('/')
def index():
	# if not session.get('userID'):
	# 	session['userID'] = uuid.uuid4().urn[9:]
	response = make_response(app.send_static_file('home.html'))
	return response

@app.route('/testsession')
def testsession():
	response = make_response(app.send_static_file('home.html'))
	if not session.get('userID'):
		return 'userID does not exist!'
	else:
		return 'userID exist'

@app.route('/sessionset')
def sessionset():
	session['userID'] = uuid.uuid4().urn[9:]
	return "userId set!"

@app.route('/sessiongetset')
def sessiongetset():
	session['userID'] = uuid.uuid4().urn[9:]
	return session['userID']

@app.route('/dicset')
def dicset():
	scheduleByUserId[session['userID']] = 'test'
	return 'dict set!'

@app.route('/dicget')
def dicget():
	return scheduleByUserId[session['userID']]

@app.route('/sessionget')
def sessionget():
	return session['userID']

@app.route('/usersession')
def usersession():
	return session['userID']

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
	try:
		if request.method == 'POST':
			f = request.files['gtfsfeedzip']
			parse_feed_scheduler(f)
			response = redirect(url_for('view_gtfs_schedule'))
			return response
	except Exception:
		exc_type, exc_value, exc_traceback = sys.exc_info()
		lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
		error = ''.join('!! ' + line for line in lines) 
		return error
	return app.send_static_file('home.html')

# equivalent of handle_GET_home(self) in schedule_viewer
@app.route('/view')
def view_gtfs_schedule():
	# We need to generate the index view
	try:
		stops = session["stops"]
		agencies = session["agencies"] 
		if stops is not None:
			(min_lat, min_lon, max_lat, max_lon) = GetStopBoundingBox(stops)
			forbid_editing = 'false'
			agency = ', '.join(a.agency_name for a in agencies).encode('utf-8')
	except Exception:
		exc_type, exc_value, exc_traceback = sys.exc_info()
		lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
		error = ''.join('!! ' + line for line in lines) 
		return error

	return render_template('index.html', data=locals())

@app.route('/json/boundboxstops')
def handle_json_GET_boundboxstops():
	"""Return a list of up to 'limit' stops within bounding box with 'n','e'
    and 's','w' in the NE and SW corners. Does not handle boxes crossing
    longitude line 180."""
	try:
		allStops = session['stops']
		params = request.args
		n = float(params.get('n'))
		e = float(params.get('e'))
		s = float(params.get('s'))
		w = float(params.get('w'))
		limit = int(params.get('limit'))
		stops = GetStopsInBoundingBox(stops=allStops,north=n, east=e, south=s, west=w, n=limit)
		return json.dumps([StopToTuple(s) for s in stops])
	except Exception, err:
		return jsonify(error='Error occured')
		# exc_type, exc_value, exc_traceback = sys.exc_info()
		# lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
		# error = ''.join('!! ' + line for line in lines) 
		# return error

@app.route('/json/routes')
def handle_json_GET_routes():
	"""Return a list of all routes."""
	result = []
	for r in session['routes']:
		result.append( (r.route_id, r.route_short_name, r.route_long_name) )
		result.sort(key = lambda x: x[1:3])
	return json.dumps(result)

@app.route('/json/routepatterns')
def handle_json_GET_routepatterns():
	#schedule = scheduleByUserId[session['userID']]
	trips = session["trips"]
	params = request.args
	route = GetRoute(session['routes'],params.get('route', None))
	if not route:
		return jsonify(message='Not found'),404

	time = int(params.get('time', 0))
	date = params.get('date', "")
  	# For each pattern return the start time for this many trips
	sample_size = 3
	pattern_id_trip_dict = GetPatternIdTripDict(route,trips)
	patterns = []
	for pattern_id, trips in pattern_id_trip_dict.items():
		# to conitnue from here
		time_stops = trips[0].GetTimeStops()
		if not time_stops:
			continue
		has_non_zero_trip_type = False;
		# Iterating over a copy so we can remove from trips inside the loop
		trips_with_service = []
		for trip in trips:
			service_id = trip.service_id
			service_period = schedule.GetServicePeriod(service_id)

			if date and not service_period.IsActiveOn(date):
				continue
			trips_with_service.append(trip)

			if trip['trip_type'] and trip['trip_type'] != '0':
				has_non_zero_trip_type = True

		# We're only interested in the trips that do run on the specified date
		trips = trips_with_service

		name = u'%s to %s, %d stops' % (time_stops[0][2].stop_name, time_stops[-1][2].stop_name, len(time_stops))
		transitfeed.SortListOfTripByTime(trips)

		num_trips = len(trips)
		if num_trips <= sample_size:
			start_sample_index = 0
			num_after_sample = 0
		else:
			# Will return sample_size trips that start after the 'time' param.
			# Linear search because I couldn't find a built-in way to do a binary
			# search with a custom key.
			start_sample_index = len(trips)
			for i, trip in enumerate(trips):
				if trip.GetStartTime() >= time:
					start_sample_index = i
					break

			num_after_sample = num_trips - (start_sample_index + sample_size)
			if num_after_sample < 0:
				# Less than sample_size trips start after 'time' so return all the
				# last sample_size trips.
				num_after_sample = 0
				start_sample_index = num_trips - sample_size

		sample = []
		for t in trips[start_sample_index:start_sample_index + sample_size]:
			sample.append( (t.GetStartTime(), t.trip_id) )

		patterns.append((name, pattern_id, start_sample_index, sample,
							num_after_sample, (0,1)[has_non_zero_trip_type]))

   	patterns.sort()
   	return json.dumps(patterns)

@app.route('/json/tripstoptimes')
def handle_json_GET_tripstoptimes():
	schedule = scheduleByUserId[session['userID']]
	params = request.args
	try:
		trip = schedule.GetTrip(params.get('trip'))
	except KeyError:
		# if a non-existent trip is searched for, the return nothing
		return jsonify(message='Not found'),404
	time_stops = trip.GetTimeStops()
	stops = []
	arrival_times = []
	departure_times = []
	for arr,dep,stop in time_stops:
		stops.append(StopToTuple(stop))
		arrival_times.append(arr)
		departure_times.append(dep)
	return jsonify([stops, arrival_times, departure_times])

@app.route('/json/tripshape')
def handle_json_GET_tripshape():
	schedule = scheduleByUserId[session['userID']]
	params = request.args
	try:
		trip = schedule.GetTrip(params.get('trip'))
	except KeyError:
		# if a non-existent trip is searched for, the return nothing
		return jsonify(message='Not found'),404
	points = []
	if trip.shape_id:
		shape = schedule.GetShape(trip.shape_id)
		for (lat, lon, dist) in shape.points:
			points.append((lat, lon))
	else:
		time_stops = trip.GetTimeStops()
		for arr,dep,stop in time_stops:
			points.append((stop.stop_lat, stop.stop_lon))
	route = schedule.GetRoute(trip.route_id)
	polyline_data = {'points': points}
	if route.route_color:
		polyline_data['color'] = '#' + route.route_color
	return jsonify(polyline_data)

@app.route('/json/stopsearch')
def handle_json_GET_stopsearch():
	params = request.args
	query = params.get('q', None).lower()
	matches = []
	stops = session['stops']
	for s in stops:
		if s.stop_id.lower().find(query) != -1 or s.stop_name.lower().find(query) != -1:
			matches.append(StopToTuple(s))
	return json.dumps(matches)

@app.route('/json/stoptrips')
def handle_json_GET_stoptrips():
	"""Given a stop_id and time in seconds since midnight return the next
	trips to visit the stop."""
	params = request.args
	stops = session['stops']
	stop = stops[params.get('stop', None)]
	time = int(params.get('time', 0))
	date = params.get('date', "")

	time_trips = stop.GetStopTimeTrips(schedule)
	time_trips.sort()  # OPT: use bisect.insort to make this O(N*ln(N)) -> O(N)
	# Keep the first 5 after param 'time'.
	# Need make a tuple to find correct bisect point
	time_trips = time_trips[bisect.bisect_left(time_trips, (time, 0)):]
	time_trips = time_trips[:5]
	# TODO: combine times for a route to show next 2 departure times
	result = []
	for time, (trip, index), tp in time_trips:
		service_id = trip.service_id
		service_period = schedule.GetServicePeriod(service_id)
		if date and not service_period.IsActiveOn(date):
			continue
		headsign = None
		# Find the most recent headsign from the StopTime objects
		for stoptime in trip.GetStopTimes()[index::-1]:
			if stoptime.stop_headsign:
				headsign = stoptime.stop_headsign
          		break
		# If stop_headsign isn't found, look for a trip_headsign
		if not headsign:
			headsign = trip.trip_headsign
		route = schedule.GetRoute(trip.route_id)
		trip_name = ''
		if route.route_short_name:
			trip_name += route.route_short_name
		if route.route_long_name:
			if len(trip_name):
				trip_name += " - "
				trip_name += route.route_long_name
		if headsign:
			trip_name += " (Direction: %s)" % headsign

      	result.append((time, (trip.trip_id, trip_name, trip.service_id), tp))
	return jsonify(result)

@app.route('/json/triprows')
def handle_json_GET_triprows():
	"""Return a list of rows from the feed file that are related to this
    trip."""
	schedule = scheduleByUserId[session['userID']]
	params = request.args
	try:
		trip = schedule.GetTrip(params.get('trip', None))
	except KeyError:
		# if a non-existent trip is searched for, the return nothing
		return
	route = schedule.GetRoute(trip.route_id)
	trip_row = dict(trip.iteritems())
	route_row = dict(route.iteritems())
	return jsonify([['trips.txt', trip_row], ['routes.txt', route_row]])

@app.route('/ttablegraph')
def handle_GET_ttablegraph():
	"""Draw a Marey graph in SVG for a pattern (collection of trips in a route
    that visit the same sequence of stops)."""
	schedule = scheduleByUserId[session['userID']]
	params = request.args
	marey = MareyGraph()
	trip = schedule.GetTrip(params.get('trip', None))
	route = schedule.GetRoute(trip.route_id)
	height = int(params.get('height', 300))

	if not route:
		print 'no such route'
		return ""

	pattern_id_trip_dict = route.GetPatternIdTripDict()
	pattern_id = trip.pattern_id
	if pattern_id not in pattern_id_trip_dict:
		print 'no pattern %s found in %s' % (pattern_id, pattern_id_trip_dict.keys())
		return ""

	triplist = pattern_id_trip_dict[pattern_id]

	pattern_start_time = min((t.GetStartTime() for t in triplist))
	pattern_end_time = max((t.GetEndTime() for t in triplist))

	marey.SetSpan(pattern_start_time,pattern_end_time)
	marey.Draw(triplist[0].GetPattern(), triplist, height)

	content = marey.Draw()

	return content

@app.route('/file/<path:filename>')
def handle_static_file_GET(filename):
	"""Return the file"""
	return app.send_static_file(filename)
  
def parse_feed_scheduler(feed):
	
	schedule = transitfeed.Schedule(problem_reporter=transitfeed.ProblemReporter())
	schedule.Load(feed)

	stops = []
	agencies = []
	routes = []
	trips = []

	# Map their entities to ours since we cant pickling them (to save them in the session)
	for value in schedule.stops.values():
		stops.append(Stop(value.stop_name,value.stop_id, value.stop_lat, value.stop_lon, value.location_type))

	for route in schedule.routes.values():
		routes.append(Route(route.route_long_name,route.route_id,route.route_short_name,route.route_type))

	for agency in schedule._agencies.values():
		agencies.append(Agency(agency.agency_name))
	
	for trip in schedule.trips.values():
		trips.append(Trip(trip.block_id,trip.route_id,trip.service_id,trip.shape_id,trip.trip_headsign,trip.trip_id))

	#pprint.pprint(schedule.trips.values())
	# save them in the session to persist them
	session["stops"] = stops
	session["routes"] = routes
	session["agencies"] = agencies
	session["trips"] = trips

	return

# @app.errorhandler(500)
# def page_not_found(e):
#     return app.send_static_file('500.html'), 500

#utils function for the JSON action to work
def StopToTuple(stop):
  """Return tuple as expected by javascript function addStopMarkerFromList"""
  return (stop.stop_id, stop.stop_name, float(stop.stop_lat),
          float(stop.stop_lon), stop.location_type)

def GetStopBoundingBox(stops):
	return (min(s.stop_lat for s in stops),
            min(s.stop_lon for s in stops),
            max(s.stop_lat for s in stops),
            max(s.stop_lon for s in stops),
           )

def GetStopsInBoundingBox(stops, north, east, south, west, n):
	"""Return a sample of up to n stops in a bounding box"""
	stop_list = []
	for s in stops:
		if (s.stop_lat <= north and s.stop_lat >= south and s.stop_lon <= east and s.stop_lon >= west):
			stop_list.append(s)
			if len(stop_list) == n:
				break
	return stop_list

def GetRoute(routes, route_id):
	return routes[route_id]

def GetPatternIdTripDict(route,trips):
	"""Return a dictionary that maps pattern_id to a list of Trip objects."""
	d = {}
	# keep trips only for this route
	route_trips = []
	for trip in trips:
		if trip.route_id == route.routeId:
			route_trips.append(trip)
	
	for t in route_trips:
		d.setdefault(t.pattern_id, []).append(t)
	
	return d

if __name__ == '__main__':
  app.run(threaded=True)