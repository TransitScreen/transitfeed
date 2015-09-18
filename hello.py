from flask import Flask, request, url_for, send_file
from feedvalidator import RunValidationOutputToFilename, ParseCommandLineArguments
import urllib
import StringIO
import transitfeed
from transitfeed import util

output_filename = 'validation-results.html'

app = Flask(__name__, static_url_path='/static')

@app.route('/')
def index():
	return app.send_static_file('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
      f = request.files['gtfsfeedzip']
      parse_file(f)
      return send_file(output_filename)

@app.route('/validate', methods=['GET', 'POST'])
def upload_url():
    if request.method == 'POST':
      url = request.form['gtfsfeedurl']
      f = StringIO.StringIO(urllib.urlopen(url).read())
      parse_file(f)
      return send_file(output_filename)

def parse_file(feed):
  # feed: GTFS file, either path of the file as a string or a file object

  parser = util.OptionParserLongError(usage='', version='%prog '+transitfeed.__version__)
  parser.set_defaults(manual_entry=False, output=output_filename,
                memory_db=False, check_duplicate_trips=False,
                limit_per_type=5, latest_version='',
                service_gap_interval=13)
  (options, args) = parser.parse_args()
  options.error_types_ignore_list = None
  options.extension = None

  exit_code = RunValidationOutputToFilename(feed,options,output_filename)
  # Exit code is 2 if an extension is provided but can't be loaded, 1 if
  # problems are found and 0 if the Schedule is problem free.
  # plain text string is '' if no other problems are found.
  # return send_from_directory(output_filename)
  return exit_code

if __name__ == '__main__':
  app.run(debug=True)
