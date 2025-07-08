import requests
from bs4 import BeautifulSoup
from flask import Flask, request, Response, make_response
import logging
import re
import html
import time

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = "a-very-good-secret-key-is-needed"  # Replace!

# --- Constants ---
BASE_URL = "https://scoring.paragleiter.org/"
# Cache active task result for a minute
AUTO_SEARCH_CACHE_DURATION = 60
MAX_TASKS_TO_CHECK = 15

# --- Caches ---
competitions_cache = None
active_task_cache = {"data": None, "timestamp": 0}


# --- Helper Functions ---
def fetch_competitions():
    global competitions_cache
    if competitions_cache is not None:
        return competitions_cache
    logger.info(f"Fetching competition list from {BASE_URL}")
    competitions = []
    try:
        response = requests.get(BASE_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        potential_links = soup.find_all("a", href=re.compile(r"^[a-z0-9\-]+/?$"))
        found_slugs = set()
        for link in potential_links:
            href = link.get("href").strip("/")
            name = link.get_text(strip=True)
            if (
                href
                and name
                and href not in found_slugs
                and not href.startswith("http")
                and len(href) > 3
            ):
                formatted_name = " ".join(
                    word.capitalize() for word in name.replace("-", " ").split()
                )
                if len(formatted_name) < 4:
                    formatted_name = name if len(name) > 3 else href.capitalize()
                competitions.append({"slug": href, "name": formatted_name})
                found_slugs.add(href)
        competitions.sort(key=lambda x: x["name"])
        if competitions:
            logger.info(f"Fetched {len(competitions)} competitions.")
            competitions_cache = competitions
        else:
            logger.warning("Could not find competition links.")
            competitions_cache = []
        return competitions_cache
    except Exception as e:
        logger.error(f"Error fetching/parsing competition list: {e}", exc_info=True)
        return []


# find_active_task (with debug mode)
def find_active_task(debug_mode=False):
    """
    Finds the currently active task.
    If debug_mode is True, returns a hardcoded test task.
    """
    if debug_mode:
        logger.info("DEBUG MODE: Simulating active task.")
        return {"competition_slug": "alpenrosen-cup-2025", "task_number": "2"}

    global active_task_cache
    now = time.time()
    if active_task_cache["data"] and (
        now - active_task_cache["timestamp"] < AUTO_SEARCH_CACHE_DURATION
    ):
        logger.info("Returning cached active task.")
        return active_task_cache["data"]
    logger.info("Searching for active task...")
    competitions = fetch_competitions()
    if not competitions:
        logger.warning("Cannot search for active task: Competition list is empty.")
        return None
    for comp in competitions:
        comp_slug = comp["slug"]
        logger.debug(f"Checking competition: {comp_slug}")
        for task_num in range(1, MAX_TASKS_TO_CHECK + 1):
            task_url = f"{BASE_URL}{comp_slug}/task{task_num}.html"
            try:
                response = requests.get(task_url, timeout=5)
                if response.status_code == 404:
                    logger.debug(f"Task {task_num} not found for {comp_slug}.")
                    break
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                h2_tags = soup.find_all("h2")
                for h2 in h2_tags:
                    h2_text = h2.get_text(" ", strip=True)
                    if f"Task {task_num}" in h2_text and "IN PROGRESS" in h2_text:
                        logger.info(
                            f"Found active task: Comp='{comp_slug}', Task='{task_num}'"
                        )
                        active_task_info = {
                            "competition_slug": comp_slug,
                            "task_number": str(task_num),
                        }
                        active_task_cache["data"] = active_task_info
                        active_task_cache["timestamp"] = now
                        return active_task_info
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout checking {task_url}")
            except requests.exceptions.RequestException as e:
                if e.response is None or e.response.status_code != 404:
                    logger.warning(f"Error checking {task_url}: {e}")
            except Exception as e:
                logger.error(f"Error parsing {task_url}: {e}", exc_info=False)
    logger.info("No active task found after checking.")
    active_task_cache["data"] = None
    active_task_cache["timestamp"] = now
    return None


# fetch_and_parse_task_results (no changes)
# ... (Keep the exact function from previous versions) ...
def fetch_and_parse_task_results(competition_slug: str, task_number: str):
    url = f"{BASE_URL}{competition_slug}/task{task_number}.html"
    logger.info(f"Fetching task results from: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching task results URL {url}: {e}")
        status_code = (
            f" (Status: {e.response.status_code})"
            if hasattr(e, "response") and e.response
            else ""
        )
        error_msg = f"Could not fetch data{status_code}."
        if hasattr(e, "response") and e.response and e.response.status_code == 404:
            error_msg = f"Task {task_number} page not found for competition '{competition_slug}' (404)."
        return f"ERROR: {error_msg}"
    try:
        soup = BeautifulSoup(response.text, "html.parser")
        all_result_tables = soup.find_all("table", class_="result")
        if len(all_result_tables) < 2:
            return (
                "ERROR: Results table structure not found or not as expected on page."
            )
        results_table = all_result_tables[1]
        rows = results_table.find_all("tr")
        parsed_results = []
        for i, row in enumerate(rows):
            if row.find("th"):
                continue
            cells = row.find_all("td")
            if len(cells) > 2:
                try:
                    rank = cells[0].get_text(strip=True)
                    pilot_id = cells[1].get_text(strip=True)
                    pilot_name = cells[2].get_text(strip=True)
                    if rank and pilot_id and pilot_name:
                        parsed_results.append(
                            {"rank": rank, "id": pilot_id, "name": pilot_name}
                        )
                except Exception:
                    pass
        if not parsed_results:
            return "ERROR: No pilot data found in the results table."
        logger.info(
            f"Successfully parsed {len(parsed_results)} pilot entries from {url}"
        )
        return parsed_results
    except Exception as e:
        logger.error(
            f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True
        )
        return f"ERROR: Could not process page data. ({e})"


# --- REVISED: HTML Page Generator for Widget ---
def generate_html_page(
    rank: str | None = None,
    error: str | None = None,
    competition_display_name: str | None = None,
    task_number: str | None = None,
) -> str:
    """Generates the HTML page for the widget, optimized for a small viewport."""
    content = ""
    title = "Pilot Rank"
    context_html = ""
    rank_color = "black"
    if competition_display_name and task_number:
        comp_esc = html.escape(competition_display_name)
        task_esc = html.escape(task_number)
        # Abbreviate for small screens
        context_html = f'<div id="context-info">{comp_esc} - T{task_esc}</div>'

    if rank:
        try:
            rank_int = int(rank)
            if rank_int == 1:
                rank_color = "gold"
            elif 2 <= rank_int <= 49:
                rank_color = "limegreen"
            elif rank_int >= 50:
                rank_color = "red"
        except (ValueError, TypeError):
            rank_color = "black"
        content = f'<div id="rank-display" style="color: {rank_color};">{html.escape(rank)}</div>'
        if context_html:
            title = f"Rank {html.escape(rank)} - {comp_esc} T{task_esc}"
        else:
            title = f"Rank: {html.escape(rank)}"
    elif error:
        content = f'<div id="error-display">{html.escape(error)}</div>'
        title = "Error"
    else:
        content = '<div id="error-display">No data</div>'
        title = "Error"

    # Simplified CSS for a small widget, with readable fonts
    html_structure = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
    <style>
        html, body {{
            height: 100%; width: 100%; margin: 0; padding: 0;
            font-family: sans-serif; background-color: transparent;
            position: relative; overflow: hidden;
            display: flex; justify-content: center; align-items: center; text-align: center;
        }}
        #context-info {{
            position: absolute; top: 5px; left: 50%; transform: translateX(-50%);
            font-size: 10px; color: black; white-space: nowrap; z-index: 10;
        }}
        #rank-display {{
            font-size: 45vh; font-weight: bold; line-height: 1;
            text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.5); z-index: 1;
        }}
        #error-display {{
            font-size: 14px; color: black; font-weight: bold;
            padding: 5px; width: 90%;
        }}
    </style></head><body>{context_html}{content}</body></html>"""
    return html_structure


# --- Simplified Root Route for Widget ---
@app.route("/", methods=["GET"])
def get_rank_widget():
    """
    Main endpoint for the rank widget.
    Expects a `pilot_id` query parameter. e.g., /?pilot_id=80227
    """
    pilot_id = request.args.get("pilot_id", "").strip()

    if not pilot_id:
        error_msg = "Pilot ID missing. Use ?pilot_id=... in URL."
        logger.warning(error_msg)
        return Response(
            generate_html_page(error=error_msg), mimetype="text/html", status=400
        )

    logger.info(f"Request for Pilot ID: {pilot_id}. Finding active task...")
    active_task_info = find_active_task()

    if not active_task_info:
        error_msg = "No active task found."
        logger.info(error_msg)
        return Response(
            generate_html_page(error=error_msg), mimetype="text/html", status=404
        )

    comp_slug = active_task_info["competition_slug"]
    task_num = active_task_info["task_number"]
    logger.info(f"Active task found: {comp_slug}/Task {task_num}. Fetching results...")

    # Look up display name for context
    competition_display_name = comp_slug
    if competitions_cache:
        for comp in competitions_cache:
            if comp["slug"] == comp_slug:
                competition_display_name = comp["name"]
                break

    results_data = fetch_and_parse_task_results(comp_slug, task_num)

    if isinstance(results_data, str) and results_data.startswith("ERROR:"):
        logger.error(f"Failed to get results for active task: {results_data}")
        error_msg = "Error loading task data."
        return Response(
            generate_html_page(
                error=error_msg,
                competition_display_name=competition_display_name,
                task_number=task_num,
            ),
            mimetype="text/html",
            status=500,
        )

    # Search for the pilot ID in the results
    found_rank = None
    for pilot in results_data:
        if pilot["id"] == pilot_id:
            found_rank = pilot["rank"]
            break

    if found_rank:
        logger.info(
            f"Pilot ID {pilot_id} found with rank {found_rank}. Displaying rank."
        )
        html_content = generate_html_page(
            rank=found_rank,
            competition_display_name=competition_display_name,
            task_number=task_num,
        )
        return Response(html_content, mimetype="text/html", status=200)
    else:
        logger.warning(
            f"Pilot ID {pilot_id} not found in active task {comp_slug}/Task {task_num}."
        )
        error_msg = f"Pilot ID {html.escape(pilot_id)} not found."
        return Response(
            generate_html_page(
                error=error_msg,
                competition_display_name=competition_display_name,
                task_number=task_num,
            ),
            mimetype="text/html",
            status=404,
        )


# --- Main Execution ---
if __name__ == "__main__":
    fetch_competitions()  # Pre-fetch competition list on startup
    logger.info("Starting Flask application...")
    app.run(host="0.0.0.0", port=5001, debug=True)  # Keep debug=True for testing
