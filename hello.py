from flask import Flask, url_for, request
from feedvalidator import RunValidationOutputToFile

app = Flask(__name__, static_url_path='/static')

@app.route('/')
def index():
	return app.send_static_file('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        f = request.files['gtfsfeedzip']
        output_filename = 'results.html'
        exit_code = RunValidationOutputToFilename(f,'',output_filename)
        # Exit code is 2 if an extension is provided but can't be loaded, 1 if
    	# problems are found and 0 if the Schedule is problem free.
    	# plain text string is '' if no other problems are found.
    	return send_from_directory(output_filename)

if __name__ == '__main__':
  app.run(debug=True)