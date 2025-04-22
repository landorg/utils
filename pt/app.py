import requests
from bs4 import BeautifulSoup
from flask import Flask, request, Response # Removed jsonify as we only return HTML now
import logging
import re # Import regular expressions

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)

# --- Constants ---
BASE_URL = "https://scoring.paragleiter.org/"

# --- Helper Functions ---

# Cache for competitions to avoid fetching on every request
competitions_cache = None

def fetch_competitions():
    """
    Fetches the list of competitions from the main scoring page.
    Returns a list of dictionaries: [{'slug': 'comp-slug', 'name': 'Competition Name'}, ...]
    Caches the result.
    """
    global competitions_cache
    if competitions_cache is not None:
        logger.info("Returning cached competitions list.")
        return competitions_cache

    logger.info(f"Fetching competition list from {BASE_URL}")
    competitions = []
    try:
        response = requests.get(BASE_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find links that likely point to competition pages.
        # This might need adjustment if the site structure changes.
        # We look for links directly within the main content area if possible,
        # or just any links matching a plausible pattern.
        # Let's look for links whose href contains only lowercase letters, numbers, and hyphens,
        # and doesn't contain typical file extensions or query parameters.
        # Often they are within <li> tags.
        potential_links = soup.find_all('a', href=re.compile(r"^[a-z0-9\-]+/?$")) # Regex for simple slugs

        found_slugs = set() # Use a set to avoid duplicates if linked multiple times

        for link in potential_links:
            href = link.get('href').strip('/') # Get href, remove leading/trailing slashes
            name = link.get_text(strip=True)

            # Basic validation: ensure it's not an empty string and looks like a slug
            if href and name and href not in found_slugs and not href.startswith("http") and len(href) > 3: # Basic filter
                # Attempt to format the name nicely (e.g., replace hyphens, title case)
                formatted_name = ' '.join(word.capitalize() for word in name.replace('-', ' ').split())
                if len(formatted_name) < 4 : # If name is too short, use the original or slug
                    formatted_name = name if len(name) > 3 else href.capitalize()

                competitions.append({'slug': href, 'name': formatted_name})
                found_slugs.add(href)
                logger.debug(f"Found competition: slug='{href}', name='{formatted_name}'")


        # Sort competitions alphabetically by name
        competitions.sort(key=lambda x: x['name'])

        if competitions:
            logger.info(f"Successfully fetched and parsed {len(competitions)} competitions.")
            competitions_cache = competitions # Cache the result
        else:
            logger.warning("Could not find any competition links matching the pattern.")
            competitions_cache = [] # Cache empty list to avoid refetching constantly on failure

        return competitions_cache

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching competition list from {BASE_URL}: {e}")
        return [] # Return empty list on error
    except Exception as e:
        logger.error(f"Error parsing competition list: {e}", exc_info=True)
        return []

# --- Keep your existing get_pilot_rank function ---
def get_pilot_rank(competition_name: str, task_number: str, pilot_id: str) -> str | None:
    """
    Fetches the results page... (rest of docstring)
    Returns the rank as a string on success, or an error string starting with "ERROR:"
    """
    # Use the slug directly if passed, otherwise sanitize
    # The form now passes the slug directly.
    # sanitized_competition_name = competition_name.strip().lower().replace(' ', '-')
    competition_slug = competition_name.strip() # Assume slug is passed now
    url = f"{BASE_URL}{competition_slug}/task{task_number}.html"
    logger.info(f"Attempting to fetch results from: {url}")

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        logger.info(f"Successfully fetched results URL: {url} with status code {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching results URL {url}: {e}")
        error_msg = f"Could not fetch data ({response.status_code})" if hasattr(e, 'response') and e.response else f"Could not fetch data ({e})"
        if hasattr(e, 'response') and e.response and e.response.status_code == 404:
             error_msg = f"Task {task_number} page not found for competition '{competition_slug}' (404)."
        return f"ERROR: {error_msg}" # Return specific error

    # ... (rest of the get_pilot_rank function remains the same as before) ...
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        all_result_tables = soup.find_all('table', class_='result')
        num_tables_found = len(all_result_tables)
        #logger.info(f"Found {num_tables_found} table(s) with class 'result'.") # Less verbose

        if num_tables_found < 2:
            #logger.warning(f"Expected at least 2 tables with class 'result', but found {num_tables_found}.")
            if num_tables_found == 1:
                 return "ERROR: Found only one results table, expected two."
            else:
                 return "ERROR: No results tables found on the page."

        results_table = all_result_tables[1]
        #logger.info("Selected the second table (index 1) for processing.")

        rows = results_table.find_all('tr')
        #logger.info(f"Found {len(rows)} rows in the selected table. Target Pilot ID: '{pilot_id}'")

        header_processed = False
        pilot_found = False
        for i, row in enumerate(rows):
            if row.find('th'):
                if not header_processed:
                    header_processed = True
                continue

            cells = row.find_all('td')
            if len(cells) > 1:
                try:
                    row_rank_cell = cells[0]
                    row_pilot_id_cell = cells[1]
                    row_rank = row_rank_cell.get_text(strip=True)
                    row_pilot_id_text = row_pilot_id_cell.get_text(strip=True)

                    # Check if the extracted pilot ID matches the target ID
                    if row_pilot_id_text == pilot_id:
                        logger.info(f"SUCCESS: Found Pilot ID '{pilot_id}' at Rank '{row_rank}'.")
                        pilot_found = True
                        return row_rank # Return the rank string
                except IndexError:
                     logger.warning(f"Row {i} in the selected table has fewer than 2 'td' cells.")
                except Exception as cell_ex:
                     logger.error(f"Error processing cells in row {i}: {cell_ex}")

        if not pilot_found:
            logger.warning(f"Pilot ID '{pilot_id}' was not found after checking all data rows in the second table.")
            return "ERROR: Pilot ID not found in results." # Simplified error

    except Exception as e:
        logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True)
        return f"ERROR: Could not process page data. ({e})"


# --- Keep your existing generate_html_page function for the rank display ---
def generate_html_page(rank: str | None = None, error: str | None = None) -> str:
    """Generates a simple HTML page to display the rank or an error with transparent background."""
    content = ""
    title = "Pilot Rank"
    if rank:
        content = f'<div id="rank-display">{rank}</div>'
        title = f"Rank: {rank}"
    elif error:
        content = f'<div id="error-display">{error}</div>'
        title = "Error"
    else:
        content = '<div id="error-display">No data available.</div>'
        title = "Error"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        html, body {{ height: 100%; margin: 0; padding: 0; font-family: sans-serif; background-color: transparent; }}
        body {{ display: flex; justify-content: center; align-items: center; text-align: center; }}
        #rank-display {{ font-size: 45vh; font-weight: bold; color: red; line-height: 1; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5); }}
        #error-display {{ font-size: 5vh; color: #eee; max-width: 80%; background-color: rgba(0, 0, 0, 0.6); padding: 15px; border-radius: 8px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.7); }}
    </style>
</head>
<body>
    {content}
</body>
</html>"""
    return html


# --- Route for displaying the rank (no changes needed here) ---
@app.route('/get_rank', methods=['GET'])
def display_rank_html():
    """ API endpoint to get pilot rank and display it in a simple HTML page. """
    # This function remains the same as the previous version
    competition = request.args.get('competition') # Expecting the slug now
    task = request.args.get('task')
    pilot_id = request.args.get('pilot_id')

    if not all([competition, task, pilot_id]):
        error_message = "ERROR: Missing required parameters: 'competition', 'task', 'pilot_id'"
        logger.warning(error_message)
        html_content = generate_html_page(error=error_message.replace("ERROR: ",""))
        return Response(html_content, mimetype='text/html', status=400)

    logger.info(f"Rank request: competition='{competition}', task='{task}', pilot_id='{pilot_id}'")
    rank_or_error = get_pilot_rank(competition, task, pilot_id) # Pass slug directly

    status_code = 200
    if rank_or_error and rank_or_error.startswith("ERROR:"):
        logger.error(f"Error processing rank request: {rank_or_error}")
        error_msg_display = rank_or_error.replace("ERROR: ","")
        if "not found" in rank_or_error.lower():
            status_code = 404
        elif "Missing required parameters" in rank_or_error:
             status_code = 400
        else:
            status_code = 500
        html_content = generate_html_page(error=error_msg_display)
    elif rank_or_error:
        logger.info(f"Successfully found rank: {rank_or_error}")
        html_content = generate_html_page(rank=rank_or_error)
    else:
        logger.error("get_pilot_rank returned None unexpectedly.")
        error_message = "An unexpected internal error occurred."
        html_content = generate_html_page(error=error_message)
        status_code = 500

    return Response(html_content, mimetype='text/html', status=status_code)


# --- NEW: Route for the Landing/Configuration Page ---
@app.route('/', methods=['GET'])
def landing_page():
    """Displays the configuration form."""
    logger.info("Serving landing page.")
    competitions = fetch_competitions() # Get (cached) list of competitions

    # Build dropdown options
    comp_options_html = ""
    if competitions:
        for comp in competitions:
            # Use html.escape if names could contain special chars, but likely safe here
            comp_options_html += f'<option value="{comp["slug"]}">{comp["name"]}</option>\n'
    else:
        comp_options_html = '<option value="" disabled>Could not load competitions</option>'

    # Generate the form HTML
    form_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Configure Rank Widget</title>
    <style>
        body {{
            font-family: sans-serif;
            line-height: 1.6;
            padding: 20px;
            max-width: 500px;
            margin: 40px auto;
            background-color: #f4f4f4;
            border: 1px solid #ddd;
            border-radius: 8px;
        }}
        h1 {{
            text-align: center;
            color: #333;
        }}
        label {{
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }}
        input[type="text"],
        input[type="number"],
        select {{
            width: 100%;
            padding: 10px;
            margin-bottom: 15px;
            border: 1px solid #ccc;
            border-radius: 4px;
            box-sizing: border-box; /* Include padding in width */
        }}
        button {{
            display: block;
            width: 100%;
            padding: 12px;
            background-color: #5cb85c;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            cursor: pointer;
            transition: background-color 0.2s;
        }}
        button:hover {{
            background-color: #4cae4c;
        }}
        .info {{
            font-size: 0.9em;
            color: #666;
            text-align: center;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <h1>Pilot Rank Widget Setup</h1>

    <form method="GET" action="/get_rank" target="_blank">
        <div>
            <label for="competition">Competition:</label>
            <select id="competition" name="competition" required>
                <option value="" disabled selected>-- Select Competition --</option>
                {comp_options_html}
            </select>
        </div>

        <div>
            <label for="task">Task Number:</label>
            <input type="number" id="task" name="task" required min="1" placeholder="e.g., 1">
        </div>

        <div>
            <label for="pilot_id">Pilot ID:</label>
            <input type="text" id="pilot_id" name="pilot_id" required placeholder="e.g., 80227">
        </div>

        <button type="submit">Show Rank</button>
    </form>

    <p class="info">
        Submit to open the rank display in a new tab/window.<br>
        Data from scoring.paragleiter.org.
    </p>

</body>
</html>
    """
    return Response(form_html, mimetype='text/html')


# --- Main Execution ---
if __name__ == '__main__':
    # Fetch competitions once on startup (optional, but good practice)
    fetch_competitions()
    logger.info("Starting Flask application...")
    # Set debug=False for deployment/stable use
    app.run(host='0.0.0.0', port=5001, debug=True)
