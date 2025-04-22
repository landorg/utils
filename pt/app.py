import requests
from bs4 import BeautifulSoup
from flask import Flask, request, Response, make_response
import logging
import re
import html

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = 'replace this with a real secret key'

# --- Constants ---
BASE_URL = "https://scoring.paragleiter.org/"
COOKIE_NAME = 'saved_pilot_id'
COOKIE_MAX_AGE = 365 * 24 * 60 * 60 # 1 year

# --- Helper Functions (fetch_competitions, fetch_and_parse_task_results) ---
# ... (These functions remain exactly the same as the previous version) ...
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


# --- Function to fetch and parse results (no changes needed here) ---
def fetch_and_parse_task_results(competition_slug: str, task_number: str):
    """ Fetches the task page, finds the second results table, and parses it. """
    # ...(rest of fetch_and_parse_task_results function remains the same)...
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
            if row.find('th'):
                if not header_skipped: header_skipped = True
                continue
            cells = row.find_all('td')
            if len(cells) > 2:
                try:
                    rank = cells[0].get_text(strip=True)
                    pilot_id = cells[1].get_text(strip=True)
                    pilot_name = cells[2].get_text(strip=True)
                    if rank and pilot_id and pilot_name:
                        parsed_results.append({'rank': rank, 'id': pilot_id, 'name': pilot_name})
                    else: logger.debug(f"Skipping row {i+1} due to missing data")
                except IndexError: logger.warning(f"Row {i+1} in the results table has fewer than 3 'td' cells.")
                except Exception as cell_ex: logger.warning(f"Error processing cells in results row {i+1}: {cell_ex}")
            else: logger.debug(f"Skipping row {i+1} as it has < 3 cells.")
        if not parsed_results:
             logger.warning(f"No valid pilot data rows found in the second table on {url}")
             return "ERROR: No pilot data found in the results table."
        logger.info(f"Successfully parsed {len(parsed_results)} pilot entries from {url}")
        return parsed_results
    except Exception as e:
        logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True)
        return f"ERROR: Could not process page data. ({e})"


# --- REVISED: generate_html_page with rank coloring and plain context ---
def generate_html_page(
    rank: str | None = None,
    error: str | None = None,
    competition_display_name: str | None = None,
    task_number: str | None = None
) -> str:
    """ Generates HTML with rank-based color and plain context info. """
    content = ""
    title = "Pilot Rank"
    context_html = ""
    rank_color = "black" # Default color

    # Prepare context string if available
    if competition_display_name and task_number:
        comp_esc = html.escape(competition_display_name)
        task_esc = html.escape(task_number)
        context_html = f'<div id="context-info">{comp_esc} - Task {task_esc}</div>'
        # Update page title logic (remains the same)

    # Determine main content (rank or error) and rank color
    if rank:
        # Determine color based on rank value
        try:
            rank_int = int(rank)
            if rank_int == 1:
                rank_color = "gold"
            elif 2 <= rank_int <= 49:
                rank_color = "limegreen" # Using limegreen for better visibility than standard green
            elif rank_int >= 50:
                rank_color = "red"
            # else: keep default black for ranks like 0 or unexpected numbers?
        except (ValueError, TypeError):
            logger.warning(f"Rank '{rank}' is not a valid integer, using default color.")
            rank_color = "black" # Use default for non-numeric ranks like DNF

        # Use inline style for the rank color
        content = f'<div id="rank-display" style="color: {rank_color};">{html.escape(rank)}</div>'
        # Update page title logic (remains the same)
        if context_html: title = f"Rank {html.escape(rank)} - {html.escape(competition_display_name)} T{html.escape(task_number)}"
        else: title = f"Rank: {html.escape(rank)}"

    elif error:
        content = f'<div id="error-display">{html.escape(error)}</div>'
        title = "Error"
    else:
        content = '<div id="error-display">No data available.</div>'
        title = "Error"

    # Construct final HTML with updated CSS
    html_structure = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        html, body {{
            height: 100%; margin: 0; padding: 0; font-family: sans-serif;
            background-color: transparent; position: relative; overflow: hidden;
        }}
        body {{
            display: flex; justify-content: center; align-items: center; text-align: center;
        }}
        #context-info {{ /* Plain black context text */
            position: absolute; top: 10px; left: 50%; transform: translateX(-50%);
            font-size: 2.5vh;
            color: black; /* CHANGED to plain black */
            white-space: nowrap; /* Keep nowrap */
            z-index: 10;
            /* Removed background, shadow, padding, border-radius */
        }}
        #rank-display {{ /* Base style for rank number */
            font-size: 45vh; font-weight: bold;
            line-height: 1;
            /* Color is now set via inline style */
            text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.5); /* Subtle dark shadow */
            z-index: 1;
        }}
        #error-display {{ /* Error styling remains the same */
            font-size: 5vh; color: #eee; max-width: 80%;
            background-color: rgba(0, 0, 0, 0.6); padding: 15px;
            border-radius: 8px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.7);
            z-index: 1;
        }}
    </style>
</head>
<body>
    {context_html}
    {content}
</body>
</html>"""
    return html_structure


# --- Route for displaying the rank (no changes needed here) ---
@app.route('/get_rank', methods=['GET'])
def display_rank_html():
    """ Gets pilot rank, displays HTML with context, and sets cookie. """
    # ...(display_rank_html function remains exactly the same as the previous version)...
    competition_slug = request.args.get('competition', '').strip()
    task = request.args.get('task', '').strip()
    pilot_id_input = request.args.get('pilot_id', '').strip()
    pilot_name_input = request.args.get('pilot_name', '').strip()
    remember_id = request.args.get('remember') == 'yes'
    if not competition_slug: return Response(generate_html_page(error="Competition not selected."), mimetype='text/html', status=400)
    if not task: return Response(generate_html_page(error="Task number not provided.", competition_display_name=competition_slug), mimetype='text/html', status=400)
    competition_display_name = competition_slug
    if competitions_cache:
        for comp in competitions_cache:
            if comp['slug'] == competition_slug:
                competition_display_name = comp['name']
                break
    else: logger.warning("Competitions cache is empty, cannot look up display name.")
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
        return Response(generate_html_page(error="Pilot ID or Pilot Name must be provided.", competition_display_name=competition_display_name, task_number=task), mimetype='text/html', status=400)
    results_data = fetch_and_parse_task_results(competition_slug, task)
    if isinstance(results_data, str) and results_data.startswith("ERROR:"):
        logger.error(f"Data fetch/parse error: {results_data}")
        status_code = 404 if "not found" in results_data.lower() else 500
        return Response(generate_html_page(error=results_data.replace("ERROR: ",""), competition_display_name=competition_display_name, task_number=task), mimetype='text/html', status=status_code)
    found_pilot_id = None
    found_rank = None
    for pilot in results_data:
        match = False
        if search_mode == 'id' and pilot['id'] == search_value: match = True
        elif search_mode == 'name' and pilot['name'].strip().lower() == search_value.strip().lower():
             match = True
             search_value = pilot['id']
        if match:
            found_pilot_id = pilot['id']
            found_rank = pilot['rank']
            logger.info(f"Found match: Rank='{found_rank}', ID='{found_pilot_id}'")
            break
    response = None
    if found_rank is not None:
        html_content = generate_html_page(rank=found_rank, competition_display_name=competition_display_name, task_number=task)
        response = make_response(html_content, 200)
        response.mimetype = 'text/html'
        if remember_id and found_pilot_id:
            logger.info(f"Setting cookie '{COOKIE_NAME}' to '{found_pilot_id}'")
            response.set_cookie(COOKIE_NAME, found_pilot_id, max_age=COOKIE_MAX_AGE, samesite='Lax')
    else:
        error_msg = f"Pilot with ID '{html.escape(pilot_id_input)}' not found." if search_mode == 'id' else f"Pilot named '{html.escape(pilot_name_input)}' not found."
        logger.warning(error_msg)
        html_content = generate_html_page(error=error_msg, competition_display_name=competition_display_name, task_number=task)
        response = make_response(html_content, 404)
        response.mimetype = 'text/html'
    return response


# --- Landing Page Route (no changes needed here) ---
@app.route('/', methods=['GET'])
def landing_page():
    """ Displays the configuration form, pre-filling ID from cookie if available. """
    # ...(landing_page function remains exactly the same as the previous version)...
    logger.info("Serving landing page.")
    saved_pilot_id = request.cookies.get(COOKIE_NAME, '')
    if saved_pilot_id: logger.info(f"Found saved pilot ID in cookie: '{saved_pilot_id}'")
    competitions = fetch_competitions()
    comp_options_html = ""
    if competitions:
        for comp in competitions:
            comp_name_esc = html.escape(comp["name"])
            comp_slug_esc = html.escape(comp["slug"])
            comp_options_html += f'<option value="{comp_slug_esc}">{comp_name_esc}</option>\n'
    else: comp_options_html = '<option value="" disabled>Could not load competitions</option>'
    saved_pilot_id_esc = html.escape(saved_pilot_id)
    form_html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Configure Rank Widget</title><style>body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 500px; margin: 40px auto; background-color: #f4f4f4; border: 1px solid #ddd; border-radius: 8px; }} h1 {{ text-align: center; color: #333; margin-bottom: 25px; }} label {{ display: block; margin-bottom: 5px; font-weight: bold; }} input[type="text"], input[type="number"], select {{ width: 100%; padding: 10px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }} .input-group {{ margin-bottom: 15px; }} .or-divider {{ text-align: center; margin: 5px 0; font-style: italic; color: #777; }} button {{ display: block; width: 100%; padding: 12px; background-color: #5cb85c; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; margin-top: 20px; }} button:hover {{ background-color: #4cae4c; }} .info {{ font-size: 0.9em; color: #666; text-align: center; margin-top: 20px; }} .checkbox-group {{ margin-top: 15px; }} .checkbox-group label {{ display: inline-block; margin-left: 5px; font-weight: normal; }} .checkbox-group input {{ width: auto; margin-bottom: 0; vertical-align: middle; }}</style></head><body><h1>Pilot Rank Widget Setup</h1><form method="GET" action="/get_rank" target="_blank"><div class="input-group"><label for="competition">Competition:</label><select id="competition" name="competition" required><option value="" disabled selected>-- Select Competition --</option>{comp_options_html}</select></div><div class="input-group"><label for="task">Task Number:</label><input type="number" id="task" name="task" required min="1" placeholder="e.g., 1"></div><div class="input-group"><label for="pilot_id">Pilot ID:</label><input type="text" id="pilot_id" name="pilot_id" placeholder="e.g., 80227 (recommended)" value="{saved_pilot_id_esc}"></div><div class="or-divider">OR</div><div class="input-group"><label for="pilot_name">Pilot Name:</label><input type="text" id="pilot_name" name="pilot_name" placeholder="e.g., John Doe (case-insensitive)"></div><div class="checkbox-group"><input type="checkbox" id="remember" name="remember" value="yes"><label for="remember">Remember my Pilot ID</label></div><button type="submit">Show Rank</button></form><p class="info">Enter Pilot ID *or* Name. Submitting opens the rank display in a new tab.<br>Data from scoring.paragleiter.org.</p></body></html>"""
    return Response(form_html, mimetype='text/html')


# --- Main Execution ---
if __name__ == '__main__':
    fetch_competitions() # Pre-fetch competition list
    logger.info("Starting Flask application...")
    app.run(host='0.0.0.0', port=5001, debug=True)
