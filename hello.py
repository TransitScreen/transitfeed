from flask import Flask, url_for, request
from feedvalidator import RunValidationOutputToFilename, ParseCommandLineArguments
import transitfeed
from transitfeed import util

app = Flask(__name__, static_url_path='/static')

@app.route('/')
def index():
	return app.send_static_file('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
    	print request
        f = request.files['gtfsfeedzip']
        output_filename = 'validation-results.html'

        parser = util.OptionParserLongError(
          usage='', version='%prog '+transitfeed.__version__)

        parser.set_defaults(manual_entry=True, output='validation-results.html',
                      memory_db=False, check_duplicate_trips=False,
                      limit_per_type=5, latest_version='',
                      service_gap_interval=13)
        (options, args) = parser.parse_args()
        options.error_types_ignore_list = None
        options.extension = None

        exit_code = RunValidationOutputToFilename(f,options,output_filename)
        # Exit code is 2 if an extension is provided but can't be loaded, 1 if
    	# problems are found and 0 if the Schedule is problem free.
    	# plain text string is '' if no other problems are found.
    	# return send_from_directory(output_filename)

    	return app.send_static_file('success.html')


if __name__ == '__main__':
  app.run(debug=True)