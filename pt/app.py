import requests
from bs4 import BeautifulSoup
# Import make_response for setting cookies
from flask import Flask, request, Response, make_response
import logging
import re

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)
# Required for secure cookies, although not strictly necessary for this simple use case.
# Replace with a real secret key in a production scenario.
app.secret_key = 'your secret key' # You can generate one using os.urandom(16)

# --- Constants ---
BASE_URL = "https://scoring.paragleiter.org/"

# --- Helper Functions ---

# Cache for competitions
competitions_cache = None

def fetch_competitions():
    """ Fetches and caches the list of competitions. """
    global competitions_cache
    if competitions_cache is not None:
        # logger.info("Returning cached competitions list.") # Less verbose
        return competitions_cache

    logger.info(f"Fetching competition list from {BASE_URL}")
    competitions = []
    try:
        response = requests.get(BASE_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        potential_links = soup.find_all('a', href=re.compile(r"^[a-z0-9\-]+/?$"))
        found_slugs = set()

        for link in potential_links:
            href = link.get('href').strip('/')
            name = link.get_text(strip=True)
            if href and name and href not in found_slugs and not href.startswith("http") and len(href) > 3:
                formatted_name = ' '.join(word.capitalize() for word in name.replace('-', ' ').split())
                if len(formatted_name) < 4 :
                    formatted_name = name if len(name) > 3 else href.capitalize()
                competitions.append({'slug': href, 'name': formatted_name})
                found_slugs.add(href)

        competitions.sort(key=lambda x: x['name'])
        if competitions:
            logger.info(f"Successfully fetched and parsed {len(competitions)} competitions.")
            competitions_cache = competitions
        else:
            logger.warning("Could not find any competition links matching the pattern.")
            competitions_cache = []
        return competitions_cache
    except Exception as e:
        logger.error(f"Error fetching or parsing competition list: {e}", exc_info=True)
        return [] # Return empty list on error

# --- Keep your existing get_pilot_rank function ---
# (No changes needed in this function itself)
def get_pilot_rank(competition_slug: str, task_number: str, pilot_id: str) -> str | None:
    """ Fetches pilot rank for a given comp/task/id. """
    url = f"{BASE_URL}{competition_slug}/task{task_number}.html"
    logger.info(f"Attempting to fetch results from: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        logger.info(f"Successfully fetched results URL: {url}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching results URL {url}: {e}")
        error_msg = f"Could not fetch data ({response.status_code})" if hasattr(e, 'response') and e.response else f"Could not fetch data ({e})"
        if hasattr(e, 'response') and e.response and e.response.status_code == 404:
             error_msg = f"Task {task_number} page not found for competition '{competition_slug}' (404)."
        return f"ERROR: {error_msg}"

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        all_result_tables = soup.find_all('table', class_='result')
        if len(all_result_tables) < 2:
             return "ERROR: Results table structure not as expected on page."

        results_table = all_result_tables[1]
        rows = results_table.find_all('tr')
        pilot_found = False
        for i, row in enumerate(rows):
            if row.find('th'): continue # Skip header
            cells = row.find_all('td')
            if len(cells) > 1:
                try:
                    row_rank = cells[0].get_text(strip=True)
                    row_pilot_id_text = cells[1].get_text(strip=True)
                    if row_pilot_id_text == pilot_id:
                        logger.info(f"SUCCESS: Found Pilot ID '{pilot_id}' at Rank '{row_rank}'.")
                        pilot_found = True
                        return row_rank
                except Exception as cell_ex:
                     logger.warning(f"Error processing cells in row {i}: {cell_ex}") # Be less noisy on errors

        if not pilot_found:
            logger.warning(f"Pilot ID '{pilot_id}' was not found in results table.")
            return "ERROR: Pilot ID not found in results."

    except Exception as e:
        logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True)
        return f"ERROR: Could not process page data. ({e})"


# --- Keep your existing generate_html_page function for the rank display ---
# (No changes needed in this function itself)
def generate_html_page(rank: str | None = None, error: str | None = None) -> str:
    """ Generates HTML for rank display or error (transparent background). """
    content = ""
    title = "Pilot Rank"
    if rank:
        content = f'<div id="rank-display">{rank}</div>'
        title = f"Rank: {rank}"
    elif error:
        content = f'<div id="error-display">{error}</div>'
        title = "Error"
    else: # Should not happen
        content = '<div id="error-display">No data available.</div>'
        title = "Error"

    # HTML structure (same as before)
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title><style>html, body {{ height: 100%; margin: 0; padding: 0; font-family: sans-serif; background-color: transparent; }} body {{ display: flex; justify-content: center; align-items: center; text-align: center; }} #rank-display {{ font-size: 45vh; font-weight: bold; color: red; line-height: 1; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5); }} #error-display {{ font-size: 5vh; color: #eee; max-width: 80%; background-color: rgba(0, 0, 0, 0.6); padding: 15px; border-radius: 8px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.7); }}</style></head><body>{content}</body></html>"""
    return html


# --- MODIFIED: Route for displaying the rank (handles cookie setting) ---
@app.route('/get_rank', methods=['GET'])
def display_rank_html():
    """ Gets pilot rank, displays HTML, and sets cookie if requested. """
    competition_slug = request.args.get('competition')
    task = request.args.get('task')
    pilot_id = request.args.get('pilot_id')
    remember_id = request.args.get('remember') == 'yes' # Check if checkbox was ticked

    # Basic validation
    if not all([competition_slug, task, pilot_id]):
        error_message = "ERROR: Missing required parameters: 'competition', 'task', 'pilot_id'"
        logger.warning(error_message)
        html_content = generate_html_page(error=error_message.replace("ERROR: ",""))
        # No cookie setting needed for this error
        return Response(html_content, mimetype='text/html', status=400)

    logger.info(f"Rank request: comp='{competition_slug}', task='{task}', id='{pilot_id}', remember='{remember_id}'")
    rank_or_error = get_pilot_rank(competition_slug, task, pilot_id)

    status_code = 200
    html_content = ""
    if rank_or_error and rank_or_error.startswith("ERROR:"):
        logger.error(f"Error processing rank request: {rank_or_error}")
        error_msg_display = rank_or_error.replace("ERROR: ","")
        if "not found" in rank_or_error.lower(): status_code = 404
        else: status_code = 500 # Treat other errors as server-side
        html_content = generate_html_page(error=error_msg_display)
        # Don't set cookie on error
        response = make_response(html_content, status_code)
        response.mimetype = 'text/html'

    elif rank_or_error: # Success
        logger.info(f"Successfully found rank: {rank_or_error}")
        html_content = generate_html_page(rank=rank_or_error)
        # Create response object using make_response
        response = make_response(html_content, status_code)
        response.mimetype = 'text/html'
        # Set cookie if requested
        if remember_id:
            logger.info(f"Setting cookie 'saved_pilot_id' to '{pilot_id}'")
            # Set cookie for 1 year (in seconds)
            max_age_seconds = 365 * 24 * 60 * 60
            response.set_cookie('saved_pilot_id', pilot_id, max_age=max_age_seconds, samesite='Lax') # samesite='Lax' is good practice
    else: # Should not happen
        logger.error("get_pilot_rank returned None unexpectedly.")
        error_message = "An unexpected internal error occurred."
        html_content = generate_html_page(error=error_message)
        status_code = 500
        response = make_response(html_content, status_code)
        response.mimetype = 'text/html'

    return response


# --- MODIFIED: Route for the Landing/Configuration Page (reads cookie) ---
@app.route('/', methods=['GET'])
def landing_page():
    """ Displays the configuration form, pre-filling ID from cookie if available. """
    logger.info("Serving landing page.")
    # Get saved pilot ID from cookie, default to empty string if not found
    saved_pilot_id = request.cookies.get('saved_pilot_id', '')
    if saved_pilot_id:
        logger.info(f"Found saved pilot ID in cookie: '{saved_pilot_id}'")

    competitions = fetch_competitions()
    comp_options_html = ""
    if competitions:
        for comp in competitions:
            comp_options_html += f'<option value="{comp["slug"]}">{comp["name"]}</option>\n'
    else:
        comp_options_html = '<option value="" disabled>Could not load competitions</option>'

    # Generate the form HTML, inserting the saved_pilot_id into the value attribute
    form_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Configure Rank Widget</title>
    <style>
        body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 500px; margin: 40px auto; background-color: #f4f4f4; border: 1px solid #ddd; border-radius: 8px; }}
        h1 {{ text-align: center; color: #333; }}
        label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
        input[type="text"], input[type="number"], select {{ width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }}
        button {{ display: block; width: 100%; padding: 12px; background-color: #5cb85c; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; }}
        button:hover {{ background-color: #4cae4c; }}
        .info {{ font-size: 0.9em; color: #666; text-align: center; margin-top: 20px; }}
        .checkbox-group label {{ display: inline-block; margin-left: 5px; font-weight: normal; }} /* Style for checkbox */
        .checkbox-group input {{ width: auto; margin-bottom: 0; vertical-align: middle; }} /* Style for checkbox */
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
            <!-- Use the saved_pilot_id (or empty string) as the initial value -->
            <input type="text" id="pilot_id" name="pilot_id" required placeholder="e.g., 80227" value="{saved_pilot_id}">
        </div>

        <!-- Checkbox for remembering ID -->
        <div class="checkbox-group">
            <input type="checkbox" id="remember" name="remember" value="yes">
            <label for="remember">Remember my Pilot ID</label>
        </div>
        <br> <!-- Add a little space before the button -->

        <button type="submit">Show Rank</button>
    </form>

    <p class="info">
        Submit to open the rank display in a new tab/window.<br>
        Data from scoring.paragleiter.org.
    </p>

</body>
</html>
    """
    # No need for make_response here, just return the HTML
    return Response(form_html, mimetype='text/html')


# --- Main Execution ---
if __name__ == '__main__':
    fetch_competitions() # Pre-fetch competition list
    logger.info("Starting Flask application...")
    # Use debug=True only for development/testing
    app.run(host='0.0.0.0', port=5001, debug=True)
