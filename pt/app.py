import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__) # Initialize the Flask application object named 'app'

# ... (keep logging setup and Flask app setup as before) ...

BASE_URL = "https://scoring.paragleiter.org/"

def get_pilot_rank(competition_name: str, task_number: str, pilot_id: str) -> str | None:
    """
    Fetches the results page for a specific competition task and finds the rank
    for a given pilot ID from the *second* table with class 'result'.
    # ... (rest of docstring)
    """
    sanitized_competition_name = competition_name.strip().lower().replace(' ', '-')
    url = f"{BASE_URL}{sanitized_competition_name}/task{task_number}.html"
    logger.info(f"Attempting to fetch URL: {url}")

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        logger.info(f"Successfully fetched URL: {url} with status code {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching URL {url}: {e}")
        if hasattr(e, 'response') and e.response is not None:
             if e.response.status_code == 404:
                 return "ERROR: Competition or task not found."
        return f"ERROR: Could not fetch data. ({e})"

    try:
        soup = BeautifulSoup(response.text, 'html.parser')

        # ***** MODIFIED PART: Find ALL tables and select the second *****
        all_result_tables = soup.find_all('table', class_='result')
        num_tables_found = len(all_result_tables)
        logger.info(f"Found {num_tables_found} table(s) with class 'result'.")

        if num_tables_found < 2:
            logger.warning(f"Expected at least 2 tables with class 'result', but found {num_tables_found}. Cannot select the second one.")
            # Return a more specific error based on how many were found
            if num_tables_found == 1:
                 return "ERROR: Found only one 'result' table, couldn't select the second."
            else: # num_tables_found == 0
                 return "ERROR: No tables with class 'result' found on the page."

        # Select the second table (index 1 because lists are 0-indexed)
        results_table = all_result_tables[1]
        logger.info("Selected the second table (index 1) for processing.")
        # ***** END OF MODIFIED PART *****

        # --- The rest of the logic remains the same, operating on results_table ---
        rows = results_table.find_all('tr')
        logger.info(f"Found {len(rows)} rows in the selected table. Target Pilot ID: '{pilot_id}'")

        header_processed = False
        pilot_found = False
        for i, row in enumerate(rows):
            if row.find('th'):
                if not header_processed:
                    logger.info("Processing header row (skipping)")
                    header_processed = True
                continue

            cells = row.find_all('td')
            if len(cells) > 1:
                try:
                    row_rank_cell = cells[0]
                    row_pilot_id_cell = cells[1]

                    row_rank = row_rank_cell.get_text(strip=True)
                    row_pilot_id = row_pilot_id_cell.get_text(strip=True)

                    # Optional: Keep detailed logging if needed for further debugging
                    logger.debug(f"Row {i}: Extracted Rank='{row_rank}', Extracted ID='{row_pilot_id}', Comparing with Target ID='{pilot_id}'")
                    # logger.debug(f"Row {i}: Comparing repr(Extracted ID)='{repr(row_pilot_id)}' with repr(Target ID)='{repr(pilot_id)}'")

                    if row_pilot_id == pilot_id:
                        logger.info(f"SUCCESS: Found matching Pilot ID '{pilot_id}' at Rank '{row_rank}' in row {i} of the second table.")
                        pilot_found = True
                        return row_rank # Return the rank
                except IndexError:
                     logger.warning(f"Row {i} in the selected table has fewer than 2 'td' cells. Content: {row.get_text(strip=True)}")
                except Exception as cell_ex:
                     logger.error(f"Error processing cells in row {i} of the selected table: {cell_ex}")
                     logger.debug(f"Row {i} HTML: {row.prettify()}")
            #else:
            #    logger.debug(f"Row {i} skipped (doesn't have enough 'td' cells).")

        if not pilot_found:
            logger.warning(f"Pilot ID '{pilot_id}' was not found after checking all data rows in the second table.")
            return "ERROR: Pilot ID not found in the second results table."

    except Exception as e:
        logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True) # Add exc_info for traceback
        return f"ERROR: Could not parse data or process tables. ({e})"


# ... (keep the Flask @app.route('/get_rank', ...) and if __name__ == '__main__': sections exactly the same) ...

@app.route('/get_rank', methods=['GET'])
def api_get_rank():
    """ API endpoint """
    competition = request.args.get('competition')
    task = request.args.get('task')
    pilot_id = request.args.get('pilot_id')

    if not all([competition, task, pilot_id]):
        logger.warning("Missing required parameters in request.")
        return jsonify({"error": "Missing required parameters: 'competition', 'task', 'pilot_id'"}), 400

    logger.info(f"Received request: competition='{competition}', task='{task}', pilot_id='{pilot_id}'")
    rank_or_error = get_pilot_rank(competition, task, pilot_id)

    if rank_or_error and rank_or_error.startswith("ERROR:"):
        logger.error(f"Error processing request: {rank_or_error}")
        status_code = 500
        if "not found" in rank_or_error.lower() or "couldn't select" in rank_or_error.lower():
            status_code = 404 # Treat table selection issues or ID not found as 404
        return jsonify({"error": rank_or_error}), status_code
    elif rank_or_error:
        logger.info(f"Successfully found rank: {rank_or_error}")
        return jsonify({"rank": rank_or_error})
    else:
         logger.error("get_pilot_rank returned None unexpectedly.")
         return jsonify({"error": "An unexpected error occurred."}), 500

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    app.run(host='0.0.0.0', port=5001, debug=True) # Keep debug=True while testing
