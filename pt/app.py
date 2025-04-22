import requests
from bs4 import BeautifulSoup
from flask import Flask, request, Response, make_response
import logging
import re
import html # For escaping potentially unsafe characters in names/IDs if needed

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = 'replace this with a real secret key' # Important for secure sessions/cookies

# --- Constants ---
BASE_URL = "https://scoring.paragleiter.org/"
COOKIE_NAME = 'saved_pilot_id'
COOKIE_MAX_AGE = 365 * 24 * 60 * 60 # 1 year

# --- Helper Functions ---

# Cache for competitions
competitions_cache = None

def fetch_competitions():
    """ Fetches and caches the list of competitions. """
    global competitions_cache
    if competitions_cache is not None: return competitions_cache
    logger.info(f"Fetching competition list from {BASE_URL}")
    competitions = []
    # ...(rest of fetch_competitions function remains the same)...
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
                if len(formatted_name) < 4 : formatted_name = name if len(name) > 3 else href.capitalize()
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
        return []


# --- NEW: Function to fetch and parse results ---
def fetch_and_parse_task_results(competition_slug: str, task_number: str):
    """
    Fetches the task page, finds the second results table, and parses it.

    Returns:
        list: A list of dicts [{'rank': str, 'id': str, 'name': str}, ...] on success.
        str: An error message string starting with "ERROR:" on failure.
    """
    url = f"{BASE_URL}{competition_slug}/task{task_number}.html"
    logger.info(f"Fetching task results from: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        logger.info(f"Successfully fetched task URL: {url}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching task URL {url}: {e}")
        status_code = f" (Status: {e.response.status_code})" if hasattr(e, 'response') and e.response else ""
        error_msg = f"Could not fetch data{status_code}."
        if hasattr(e, 'response') and e.response and e.response.status_code == 404:
            error_msg = f"Task {task_number} page not found for competition '{competition_slug}' (404)."
        return f"ERROR: {error_msg}"

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        all_result_tables = soup.find_all('table', class_='result')
        if len(all_result_tables) < 2:
            logger.warning(f"Expected 2+ tables with class 'result', found {len(all_result_tables)} on {url}")
            return "ERROR: Results table structure not found or not as expected on page."

        results_table = all_result_tables[1] # Use the second table
        rows = results_table.find_all('tr')
        parsed_results = []
        header_skipped = False

        for i, row in enumerate(rows):
            if row.find('th'): # Skip header row(s)
                if not header_skipped:
                    # logger.debug("Skipping header row")
                    header_skipped = True
                continue

            cells = row.find_all('td')
            # Expecting at least Rank (0), ID (1), Name (2)
            if len(cells) > 2:
                try:
                    rank = cells[0].get_text(strip=True)
                    pilot_id = cells[1].get_text(strip=True)
                    # Be careful with name extraction, might contain extra links/images sometimes?
                    # .get_text() usually handles this reasonably well.
                    pilot_name = cells[2].get_text(strip=True)

                    # Basic validation
                    if rank and pilot_id and pilot_name:
                        parsed_results.append({
                            'rank': rank,
                            'id': pilot_id,
                            'name': pilot_name
                        })
                    else:
                        logger.debug(f"Skipping row {i+1} due to missing data: rank='{rank}', id='{pilot_id}', name='{pilot_name}'")

                except IndexError:
                    logger.warning(f"Row {i+1} in the results table has fewer than 3 'td' cells.")
                except Exception as cell_ex:
                    logger.warning(f"Error processing cells in results row {i+1}: {cell_ex}")
            else:
                 logger.debug(f"Skipping row {i+1} as it has < 3 cells.")


        if not parsed_results:
             logger.warning(f"No valid pilot data rows found in the second table on {url}")
             return "ERROR: No pilot data found in the results table."

        logger.info(f"Successfully parsed {len(parsed_results)} pilot entries from {url}")
        return parsed_results # Return the list of dictionaries

    except Exception as e:
        logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True)
        return f"ERROR: Could not process page data. ({e})"


# --- Keep existing generate_html_page function (no changes needed) ---
def generate_html_page(rank: str | None = None, error: str | None = None) -> str:
    """ Generates HTML for rank display or error (transparent background). """
    content = ""
    title = "Pilot Rank"
    if rank:
        content = f'<div id="rank-display">{html.escape(rank)}</div>' # Escape rank just in case
        title = f"Rank: {html.escape(rank)}"
    elif error:
        content = f'<div id="error-display">{html.escape(error)}</div>' # Escape error message
        title = "Error"
    else: # Should not happen
        content = '<div id="error-display">No data available.</div>'
        title = "Error"
    # HTML structure (same as before)
    html_structure = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title><style>html, body {{ height: 100%; margin: 0; padding: 0; font-family: sans-serif; background-color: transparent; }} body {{ display: flex; justify-content: center; align-items: center; text-align: center; }} #rank-display {{ font-size: 45vh; font-weight: bold; color: red; line-height: 1; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5); }} #error-display {{ font-size: 5vh; color: #eee; max-width: 80%; background-color: rgba(0, 0, 0, 0.6); padding: 15px; border-radius: 8px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.7); }}</style></head><body>{content}</body></html>"""
    return html_structure


# --- REVISED: Route for displaying the rank (searches parsed data) ---
@app.route('/get_rank', methods=['GET'])
def display_rank_html():
    """
    Gets pilot rank by ID or Name, displays HTML, and sets cookie if requested.
    """
    competition_slug = request.args.get('competition', '').strip()
    task = request.args.get('task', '').strip()
    pilot_id_input = request.args.get('pilot_id', '').strip()
    pilot_name_input = request.args.get('pilot_name', '').strip()
    remember_id = request.args.get('remember') == 'yes'

    # --- Input Validation ---
    if not competition_slug:
        return Response(generate_html_page(error="Competition not selected."), mimetype='text/html', status=400)
    if not task:
        return Response(generate_html_page(error="Task number not provided."), mimetype='text/html', status=400)

    # Determine search criteria (Prioritize ID if both are given)
    search_mode = None
    search_value = None
    if pilot_id_input:
        search_mode = 'id'
        search_value = pilot_id_input
        logger.info(f"Rank request: comp='{competition_slug}', task='{task}', search by ID='{search_value}', remember='{remember_id}'")
    elif pilot_name_input:
        search_mode = 'name'
        search_value = pilot_name_input
        logger.info(f"Rank request: comp='{competition_slug}', task='{task}', search by NAME='{search_value}', remember='{remember_id}'")
    else:
        return Response(generate_html_page(error="Pilot ID or Pilot Name must be provided."), mimetype='text/html', status=400)

    # --- Fetch and Parse Data ---
    results_data = fetch_and_parse_task_results(competition_slug, task)

    # Handle fetch/parse errors
    if isinstance(results_data, str) and results_data.startswith("ERROR:"):
        logger.error(f"Data fetch/parse error: {results_data}")
        status_code = 404 if "not found" in results_data.lower() else 500
        return Response(generate_html_page(error=results_data.replace("ERROR: ","")), mimetype='text/html', status=status_code)

    # --- Search within Parsed Data ---
    found_pilot_id = None
    found_rank = None
    found_name = None # Store the name corresponding to the found ID

    for pilot in results_data:
        match = False
        if search_mode == 'id' and pilot['id'] == search_value:
            match = True
        elif search_mode == 'name' and pilot['name'].strip().lower() == search_value.strip().lower(): # Case-insensitive name match
             match = True
             # If searching by name, we found the name, record the corresponding ID
             search_value = pilot['id'] # Update search_value to the ID for cookie setting consistency

        if match:
            found_pilot_id = pilot['id']
            found_rank = pilot['rank']
            found_name = pilot['name']
            logger.info(f"Found match: Rank='{found_rank}', ID='{found_pilot_id}', Name='{found_name}'")
            break # Stop after first match

    # --- Generate Response ---
    response = None
    if found_rank is not None: # Success
        html_content = generate_html_page(rank=found_rank)
        response = make_response(html_content, 200)
        response.mimetype = 'text/html'
        # Set cookie if requested AND we have a definitive pilot ID
        if remember_id and found_pilot_id:
            logger.info(f"Setting cookie '{COOKIE_NAME}' to '{found_pilot_id}'")
            response.set_cookie(COOKIE_NAME, found_pilot_id, max_age=COOKIE_MAX_AGE, samesite='Lax')
        elif not remember_id and request.cookies.get(COOKIE_NAME):
             # Optional: Clear cookie if "remember" is unchecked and cookie exists?
             # logger.info(f"Clearing cookie '{COOKIE_NAME}'")
             # response.delete_cookie(COOKIE_NAME)
             pass # Decide if unchecking should clear it. For now, it doesn't.
    else: # Not found
        error_msg = f"Pilot with ID '{pilot_id_input}' not found." if search_mode == 'id' else f"Pilot named '{pilot_name_input}' not found."
        logger.warning(error_msg)
        html_content = generate_html_page(error=error_msg)
        response = make_response(html_content, 404)
        response.mimetype = 'text/html'

    return response


# --- REVISED: Route for the Landing/Configuration Page ---
@app.route('/', methods=['GET'])
def landing_page():
    """ Displays the configuration form, pre-filling ID from cookie if available. """
    logger.info("Serving landing page.")
    saved_pilot_id = request.cookies.get(COOKIE_NAME, '')
    if saved_pilot_id:
        logger.info(f"Found saved pilot ID in cookie: '{saved_pilot_id}'")

    competitions = fetch_competitions()
    comp_options_html = ""
    if competitions:
        for comp in competitions:
            # Escape potential special characters in names/slugs for safety
            comp_name_esc = html.escape(comp["name"])
            comp_slug_esc = html.escape(comp["slug"])
            comp_options_html += f'<option value="{comp_slug_esc}">{comp_name_esc}</option>\n'
    else:
        comp_options_html = '<option value="" disabled>Could not load competitions</option>'

    # Use html.escape for the pre-filled pilot ID value
    saved_pilot_id_esc = html.escape(saved_pilot_id)

    # Generate the form HTML
    form_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Configure Rank Widget</title>
    <style>
        body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 500px; margin: 40px auto; background-color: #f4f4f4; border: 1px solid #ddd; border-radius: 8px; }}
        h1 {{ text-align: center; color: #333; margin-bottom: 25px; }}
        label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
        input[type="text"], input[type="number"], select {{ width: 100%; padding: 10px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }}
        .input-group {{ margin-bottom: 15px; }}
        .or-divider {{ text-align: center; margin: 5px 0; font-style: italic; color: #777; }}
        button {{ display: block; width: 100%; padding: 12px; background-color: #5cb85c; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; margin-top: 20px; }}
        button:hover {{ background-color: #4cae4c; }}
        .info {{ font-size: 0.9em; color: #666; text-align: center; margin-top: 20px; }}
        .checkbox-group {{ margin-top: 15px; }}
        .checkbox-group label {{ display: inline-block; margin-left: 5px; font-weight: normal; }}
        .checkbox-group input {{ width: auto; margin-bottom: 0; vertical-align: middle; }}
    </style>
</head>
<body>
    <h1>Pilot Rank Widget Setup</h1>

    <form method="GET" action="/get_rank" target="_blank">
        <div class="input-group">
            <label for="competition">Competition:</label>
            <select id="competition" name="competition" required>
                <option value="" disabled selected>-- Select Competition --</option>
                {comp_options_html}
            </select>
        </div>

        <div class="input-group">
            <label for="task">Task Number:</label>
            <input type="number" id="task" name="task" required min="1" placeholder="e.g., 1">
        </div>

        <div class="input-group">
            <label for="pilot_id">Pilot ID:</label>
            <input type="text" id="pilot_id" name="pilot_id" placeholder="e.g., 80227 (recommended)" value="{saved_pilot_id_esc}">
        </div>

        <div class="or-divider">OR</div>

        <div class="input-group">
            <label for="pilot_name">Pilot Name:</label>
            <input type="text" id="pilot_name" name="pilot_name" placeholder="e.g., John Doe (case-insensitive)">
        </div>

        <div class="checkbox-group">
            <input type="checkbox" id="remember" name="remember" value="yes">
            <label for="remember">Remember my Pilot ID</label>
        </div>

        <button type="submit">Show Rank</button>
    </form>

    <p class="info">
        Enter Pilot ID *or* Name. Submitting opens the rank display in a new tab.<br>
        Data from scoring.paragleiter.org.
    </p>

</body>
</html>
    """
    return Response(form_html, mimetype='text/html')


# --- Main Execution ---
if __name__ == '__main__':
    fetch_competitions() # Pre-fetch competition list
    logger.info("Starting Flask application...")
    # Set debug=False for deployment/stable use
    app.run(host='0.0.0.0', port=5001, debug=True) # Keep debug=True while testing
