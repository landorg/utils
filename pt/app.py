import requests
from bs4 import BeautifulSoup
from flask import Flask, request, Response, make_response
import logging
import re
import html
import time

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = 'a-very-good-secret-key-is-needed' # Replace!

# --- Constants ---
BASE_URL = "https://scoring.paragleiter.org/"
COOKIE_NAME = 'saved_pilot_id'
COOKIE_MAX_AGE = 365 * 24 * 60 * 60 # 1 year
AUTO_SEARCH_CACHE_DURATION = 300 # Cache active task result for 5 minutes
MAX_TASKS_TO_CHECK = 15

# --- Caches ---
competitions_cache = None
active_task_cache = {"data": None, "timestamp": 0}

# --- Helper Functions ---

# fetch_competitions (no changes)
# ... (Keep the exact function from previous versions) ...
def fetch_competitions():
    global competitions_cache
    if competitions_cache is not None: return competitions_cache
    logger.info(f"Fetching competition list from {BASE_URL}")
    competitions = []
    try:
        response = requests.get(BASE_URL, timeout=10); response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        potential_links = soup.find_all('a', href=re.compile(r"^[a-z0-9\-]+/?$"))
        found_slugs = set()
        for link in potential_links:
            href = link.get('href').strip('/'); name = link.get_text(strip=True)
            if href and name and href not in found_slugs and not href.startswith("http") and len(href) > 3:
                formatted_name = ' '.join(word.capitalize() for word in name.replace('-', ' ').split())
                if len(formatted_name) < 4 : formatted_name = name if len(name) > 3 else href.capitalize()
                competitions.append({'slug': href, 'name': formatted_name}); found_slugs.add(href)
        competitions.sort(key=lambda x: x['name'])
        if competitions: logger.info(f"Fetched {len(competitions)} competitions."); competitions_cache = competitions
        else: logger.warning("Could not find competition links."); competitions_cache = []
        return competitions_cache
    except Exception as e: logger.error(f"Error fetching/parsing competition list: {e}", exc_info=True); return []

# find_active_task (no changes)
# ... (Keep the exact function from previous versions) ...
def find_active_task():
    global active_task_cache; now = time.time()
    if active_task_cache["data"] and (now - active_task_cache["timestamp"] < AUTO_SEARCH_CACHE_DURATION):
        logger.info("Returning cached active task."); return active_task_cache["data"]
    logger.info("Searching for active task...")
    competitions = fetch_competitions()
    if not competitions: logger.warning("Cannot search for active task: Competition list is empty."); return None
    for comp in competitions:
        comp_slug = comp['slug']; logger.debug(f"Checking competition: {comp_slug}")
        for task_num in range(1, MAX_TASKS_TO_CHECK + 1):
            task_url = f"{BASE_URL}{comp_slug}/task{task_num}.html"
            try:
                response = requests.get(task_url, timeout=5);
                if response.status_code == 404: logger.debug(f"Task {task_num} not found for {comp_slug}."); break
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser'); h2_tags = soup.find_all('h2')
                for h2 in h2_tags:
                    h2_text = h2.get_text(" ", strip=True)
                    if f"Task {task_num}" in h2_text and "(IN PROGRESS)" in h2_text:
                        logger.info(f"Found active task: Comp='{comp_slug}', Task='{task_num}'")
                        active_task_info = {'competition_slug': comp_slug, 'task_number': str(task_num)}
                        active_task_cache["data"] = active_task_info; active_task_cache["timestamp"] = now
                        return active_task_info
            except requests.exceptions.Timeout: logger.warning(f"Timeout checking {task_url}")
            except requests.exceptions.RequestException as e:
                if e.response is None or e.response.status_code != 404: logger.warning(f"Error checking {task_url}: {e}")
            except Exception as e: logger.error(f"Error parsing {task_url}: {e}", exc_info=False)
    logger.info("No active task found after checking.")
    active_task_cache["data"] = None; active_task_cache["timestamp"] = now
    return None


# fetch_and_parse_task_results (no changes)
# ... (Keep the exact function from previous versions) ...
def fetch_and_parse_task_results(competition_slug: str, task_number: str):
    url = f"{BASE_URL}{competition_slug}/task{task_number}.html"; logger.info(f"Fetching task results from: {url}")
    try: response = requests.get(url, timeout=15); response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching task results URL {url}: {e}")
        status_code = f" (Status: {e.response.status_code})" if hasattr(e, 'response') and e.response else ""
        error_msg = f"Could not fetch data{status_code}."
        if hasattr(e, 'response') and e.response and e.response.status_code == 404: error_msg = f"Task {task_number} page not found for competition '{competition_slug}' (404)."
        return f"ERROR: {error_msg}"
    try:
        soup = BeautifulSoup(response.text, 'html.parser'); all_result_tables = soup.find_all('table', class_='result')
        if len(all_result_tables) < 2: return "ERROR: Results table structure not found or not as expected on page."
        results_table = all_result_tables[1]; rows = results_table.find_all('tr'); parsed_results = []
        for i, row in enumerate(rows):
            if row.find('th'): continue
            cells = row.find_all('td')
            if len(cells) > 2:
                try:
                    rank = cells[0].get_text(strip=True); pilot_id = cells[1].get_text(strip=True); pilot_name = cells[2].get_text(strip=True)
                    if rank and pilot_id and pilot_name: parsed_results.append({'rank': rank, 'id': pilot_id, 'name': pilot_name})
                except Exception: pass
        if not parsed_results: return "ERROR: No pilot data found in the results table."
        logger.info(f"Successfully parsed {len(parsed_results)} pilot entries from {url}")
        return parsed_results
    except Exception as e: logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True); return f"ERROR: Could not process page data. ({e})"


# generate_html_page (no changes)
# ... (Keep the exact function from previous versions with rank coloring) ...
def generate_html_page(rank: str | None = None, error: str | None = None, competition_display_name: str | None = None, task_number: str | None = None) -> str:
    content = ""; title = "Pilot Rank"; context_html = ""; rank_color = "black"
    if competition_display_name and task_number:
        comp_esc = html.escape(competition_display_name); task_esc = html.escape(task_number)
        context_html = f'<div id="context-info">{comp_esc} - Task {task_esc}</div>'
    if rank:
        try:
            rank_int = int(rank)
            if rank_int == 1: rank_color = "gold"
            elif 2 <= rank_int <= 49: rank_color = "limegreen"
            elif rank_int >= 50: rank_color = "red"
        except (ValueError, TypeError): rank_color = "black"
        content = f'<div id="rank-display" style="color: {rank_color};">{html.escape(rank)}</div>'
        if context_html: title = f"Rank {html.escape(rank)} - {html.escape(competition_display_name)} T{html.escape(task_number)}"
        else: title = f"Rank: {html.escape(rank)}"
    elif error: content = f'<div id="error-display">{html.escape(error)}</div>'; title = "Error"
    else: content = '<div id="error-display">No data available.</div>'; title = "Error"
    html_structure = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title><style>html, body {{ height: 100%; margin: 0; padding: 0; font-family: sans-serif; background-color: transparent; position: relative; overflow: hidden; }} body {{ display: flex; justify-content: center; align-items: center; text-align: center; }} #context-info {{ position: absolute; top: 10px; left: 50%; transform: translateX(-50%); font-size: 2.5vh; color: black; white-space: nowrap; z-index: 10; }} #rank-display {{ font-size: 45vh; font-weight: bold; line-height: 1; text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.5); z-index: 1; }} #error-display {{ font-size: 5vh; color: #eee; max-width: 80%; background-color: rgba(0, 0, 0, 0.6); padding: 15px; border-radius: 8px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.7); z-index: 1; }}</style></head><body>{context_html}{content}</body></html>"""
    return html_structure


# --- NEW HELPER: Render Configuration Form ---
def render_configuration_form(saved_pilot_id='', message=None):
    """Generates the HTML for the configuration form page."""
    logger.info(f"Rendering configuration form. Saved ID: '{saved_pilot_id}', Message: '{message}'")
    competitions = fetch_competitions()
    comp_options_html = ""
    if competitions:
        for comp in competitions:
            comp_name_esc = html.escape(comp["name"]); comp_slug_esc = html.escape(comp["slug"])
            comp_options_html += f'<option value="{comp_slug_esc}">{comp_name_esc}</option>\n'
    else: comp_options_html = '<option value="" disabled>Could not load competitions</option>'
    saved_pilot_id_esc = html.escape(saved_pilot_id)
    message_html = f'<p class="status-message">{html.escape(message)}</p>' if message else ""

    form_html = f"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Configure Rank Widget</title>
    <style>
        body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 500px; margin: 40px auto; background-color: #f4f4f4; border: 1px solid #ddd; border-radius: 8px; }}
        h1 {{ text-align: center; color: #333; margin-bottom: 15px; }}
        .status-message {{ text-align: center; color: #d9534f; background-color: #f2dede; border: 1px solid #ebccd1; padding: 10px; border-radius: 4px; margin-bottom: 15px; }} /* Style for messages */
        label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
        input[type="text"], input[type="number"], select {{ width: 100%; padding: 10px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }}
        .input-group {{ margin-bottom: 15px; }}
        button {{ display: block; width: 100%; padding: 12px; background-color: #5cb85c; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; transition: background-color 0.2s; margin-top: 20px; }}
        button:hover {{ background-color: #4cae4c; }}
        .info {{ font-size: 0.9em; color: #666; text-align: center; margin-top: 10px; margin-bottom: 20px; }}
        .checkbox-group {{ margin-top: 5px; margin-bottom: 15px; }}
        .checkbox-group label {{ display: inline-block; margin-left: 5px; font-weight: normal; }}
        .checkbox-group input {{ width: auto; margin-bottom: 0; vertical-align: middle; }}
        #manual-selection {{ display: none; border-top: 1px dashed #ccc; margin-top: 25px; padding-top: 20px; }}
        .manual-toggle {{ text-align: center; margin-top: 20px; }}
        .manual-toggle a {{ color: #337ab7; cursor: pointer; text-decoration: underline; }}
        .or-divider {{ text-align: center; margin: 5px 0; font-style: italic; color: #777; }}
    </style>
    <script>function toggleManual() {{ var d=document.getElementById('manual-selection'), l=document.getElementById('manual-toggle-link'); if (d.style.display==='none'||d.style.display===''){{d.style.display='block';l.textContent='[Hide Manual Options]';}} else {{d.style.display='none';l.textContent='[Manual Selection...]';}} }} </script>
</head><body><h1>Pilot Rank Widget Setup</h1>{message_html}
    <form method="GET" action="/get_rank" target="_blank">
        <p class="info">Enter your Pilot ID for automatic lookup. If that fails, use Manual Selection.</p>
        <div class="input-group"><label for="pilot_id">Pilot ID:</label><input type="text" id="pilot_id" name="pilot_id" required placeholder="Your Pilot ID (e.g., 80227)" value="{saved_pilot_id_esc}"></div>
        <div class="or-divider">AND/OR</div>
        <div class="input-group"><label for="pilot_name">Pilot Name (Optional):</label><input type="text" id="pilot_name" name="pilot_name" placeholder="e.g., John Doe (if ID unknown)"></div>
        <button type="submit">Show My Rank</button>
        <div class="manual-toggle"><a id="manual-toggle-link" onclick="toggleManual()" href="javascript:void(0);">[Manual Selection...]</a></div>
        <div id="manual-selection">
            <p class="info">Manual Selection:</p>
            <div class="input-group"><label for="competition">Competition:</label><select id="competition" name="competition"><option value="" disabled selected>-- Select Competition --</option>{comp_options_html}</select></div>
            <div class="input-group"><label for="task">Task Number:</label><input type="number" id="task" name="task" min="1" placeholder="e.g., 1"></div>
        </div>
    </form></body></html>"""
    return Response(form_html, mimetype='text/html')


# --- REVISED: Root Route ('/') ---
@app.route('/', methods=['GET'])
def landing_or_auto_rank():
    """ Tries direct auto-rank if cookie exists, otherwise shows config form. """
    saved_pilot_id = request.cookies.get(COOKIE_NAME, '')

    if saved_pilot_id:
        logger.info(f"Cookie found for Pilot ID: {saved_pilot_id}. Attempting auto-rank.")
        active_task_info = find_active_task()

        if active_task_info:
            comp_slug = active_task_info['competition_slug']
            task_num = active_task_info['task_number']
            logger.info(f"Active task found: {comp_slug} / Task {task_num}. Fetching results...")

            results_data = fetch_and_parse_task_results(comp_slug, task_num)

            if isinstance(results_data, str) and results_data.startswith("ERROR:"):
                # Fetching/parsing the specific active task failed
                logger.error(f"Failed to get results for active task: {results_data}")
                return render_configuration_form(saved_pilot_id=saved_pilot_id, message="Error loading data for the active task. Please use manual selection.")

            # Search for the pilot ID from the cookie in the results
            found_rank = None
            for pilot in results_data:
                if pilot['id'] == saved_pilot_id:
                    found_rank = pilot['rank']
                    break

            if found_rank:
                # Success! Display rank directly
                logger.info(f"Pilot ID {saved_pilot_id} found in active task with rank {found_rank}. Displaying rank.")
                # Look up display name
                competition_display_name = comp_slug
                if competitions_cache:
                    for comp in competitions_cache:
                        if comp['slug'] == comp_slug: competition_display_name = comp['name']; break
                # Generate HTML page
                html_content = generate_html_page(rank=found_rank, competition_display_name=competition_display_name, task_number=task_num)
                # No need to set cookie here, just display
                return Response(html_content, mimetype='text/html', status=200)
            else:
                # Pilot ID from cookie was NOT found in the active task's results
                logger.warning(f"Pilot ID {saved_pilot_id} (from cookie) not found in active task {comp_slug}/Task {task_num}.")
                return render_configuration_form(saved_pilot_id=saved_pilot_id, message="Your saved ID was not found in the current active task. Please check ID or use manual selection.")

        else:
            # No active task could be found
            logger.info("No active task found via auto-search.")
            return render_configuration_form(saved_pilot_id=saved_pilot_id, message="Could not automatically find an active task. Please use manual selection.")
    else:
        # No cookie, show the configuration form directly
        logger.info("No pilot ID cookie found. Showing configuration form.")
        return render_configuration_form()


# --- REVISED: /get_rank Route (Handles form submission ONLY) ---
@app.route('/get_rank', methods=['GET'])
def handle_form_submission_rank():
    """ Handles rank requests submitted via the form (auto or manual). """
    competition_slug = request.args.get('competition', '').strip()
    task = request.args.get('task', '').strip()
    pilot_id_input = request.args.get('pilot_id', '').strip()
    pilot_name_input = request.args.get('pilot_name', '').strip()

    # Determine search criteria (ID or Name required)
    search_mode = None; search_value = None
    if pilot_id_input: search_mode = 'id'; search_value = pilot_id_input
    elif pilot_name_input: search_mode = 'name'; search_value = pilot_name_input
    else: return Response(generate_html_page(error="Pilot ID or Pilot Name must be provided from form."), mimetype='text/html', status=400)

    # Determine comp/task (Manual or Auto)
    comp_to_use = None; task_to_use = None
    if competition_slug and task: # Manual parameters provided
        manual_mode = True
        comp_to_use = competition_slug
        task_to_use = task
        logger.info(f"Manual form submission: comp='{comp_to_use}', task='{task_to_use}', search by {search_mode}='{search_value}'")
    else: # Auto mode triggered from form (no comp/task provided)
        manual_mode = False
        logger.info(f"Auto form submission: search by {search_mode}='{search_value}'. Finding active task...")
        active_task_info = find_active_task()
        if active_task_info:
            comp_to_use = active_task_info['competition_slug']
            task_to_use = active_task_info['task_number']
            logger.info(f"Auto-detected active task: Comp='{comp_to_use}', Task='{task_to_use}'")
        else:
            # Auto search from form failed
            return Response(generate_html_page(error="Could not automatically find an active task. Please use Manual Selection on the form."), mimetype='text/html', status=404)

    # --- Proceed with Fetch, Parse, Search, Respond (identical to previous /get_rank logic) ---
    competition_display_name = comp_to_use
    if competitions_cache:
        for comp in competitions_cache:
            if comp['slug'] == comp_to_use: competition_display_name = comp['name']; break

    results_data = fetch_and_parse_task_results(comp_to_use, task_to_use)
    if isinstance(results_data, str) and results_data.startswith("ERROR:"):
        logger.error(f"Data fetch/parse error: {results_data}")
        status_code = 404 if "not found" in results_data.lower() else 500
        return Response(generate_html_page(error=results_data.replace("ERROR: ",""), competition_display_name=competition_display_name, task_number=task_to_use), mimetype='text/html', status=status_code)

    found_pilot_id = None; found_rank = None
    for pilot in results_data:
        match = False; current_id = pilot['id']; current_name = pilot['name']
        if search_mode == 'id' and current_id == search_value: match = True
        elif search_mode == 'name' and current_name.strip().lower() == search_value.strip().lower():
             match = True; search_value = current_id # Use found ID for cookie
        if match: found_pilot_id = current_id; found_rank = pilot['rank']; logger.info(f"Found match: Rank='{found_rank}', ID='{found_pilot_id}'"); break

    response = None
    if found_rank is not None: # Success
        html_content = generate_html_page(rank=found_rank, competition_display_name=competition_display_name, task_number=task_to_use)
        response = make_response(html_content, 200)
    else: # Not found
        error_msg = f"Pilot with ID '{html.escape(pilot_id_input)}' not found." if search_mode == 'id' else f"Pilot named '{html.escape(pilot_name_input)}' not found."
        logger.warning(f"{error_msg} in {comp_to_use}/Task {task_to_use}")
        html_content = generate_html_page(error=error_msg, competition_display_name=competition_display_name, task_number=task_to_use)
        response = make_response(html_content, 404)

    response.mimetype = 'text/html'
    logger.info(f"Setting cookie '{COOKIE_NAME}' to '{found_pilot_id}'")
    response.set_cookie(COOKIE_NAME, found_pilot_id, max_age=COOKIE_MAX_AGE, samesite='Lax')

    return response


# --- Main Execution ---
if __name__ == '__main__':
    fetch_competitions() # Pre-fetch competition list on startup
    logger.info("Starting Flask application...")
    app.run(host='0.0.0.0', port=5001, debug=True) # Keep debug=True for testing
