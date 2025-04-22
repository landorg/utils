import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, Response # Import Response
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask App
app = Flask(__name__)

BASE_URL = "https://scoring.paragleiter.org/"

# --- Keep your existing get_pilot_rank function ---
# (Make sure it returns strings like "ERROR: ..." on failure
# and the rank as a string on success)
def get_pilot_rank(competition_name: str, task_number: str, pilot_id: str) -> str | None:
    """
    Fetches the results page for a specific competition task and finds the rank
    for a given pilot ID from the *second* table with class 'result'.
    Returns the rank as a string on success, or an error string starting with "ERROR:"
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
        error_msg = f"Could not fetch data ({response.status_code})" if hasattr(e, 'response') and e.response else f"Could not fetch data ({e})"
        if hasattr(e, 'response') and e.response and e.response.status_code == 404:
             error_msg = "Competition or task page not found (404)."
        return f"ERROR: {error_msg}" # Return specific error

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        all_result_tables = soup.find_all('table', class_='result')
        num_tables_found = len(all_result_tables)
        logger.info(f"Found {num_tables_found} table(s) with class 'result'.")

        if num_tables_found < 2:
            logger.warning(f"Expected at least 2 tables with class 'result', but found {num_tables_found}.")
            if num_tables_found == 1:
                 return "ERROR: Found only one results table, expected two."
            else:
                 return "ERROR: No results tables found on the page."

        results_table = all_result_tables[1]
        logger.info("Selected the second table (index 1) for processing.")

        rows = results_table.find_all('tr')
        logger.info(f"Found {len(rows)} rows in the selected table. Target Pilot ID: '{pilot_id}'")

        header_processed = False
        pilot_found = False
        for i, row in enumerate(rows):
            if row.find('th'):
                if not header_processed:
                    # logger.info("Processing header row (skipping)") # Less verbose now
                    header_processed = True
                continue

            cells = row.find_all('td')
            if len(cells) > 1:
                try:
                    row_rank_cell = cells[0]
                    row_pilot_id_cell = cells[1]
                    row_rank = row_rank_cell.get_text(strip=True)
                    row_pilot_id = row_pilot_id_cell.get_text(strip=True)

                    if row_pilot_id == pilot_id:
                        logger.info(f"SUCCESS: Found Pilot ID '{pilot_id}' at Rank '{row_rank}' in row {i} of the second table.")
                        pilot_found = True
                        return row_rank # Return the rank string
                except IndexError:
                     logger.warning(f"Row {i} in the selected table has fewer than 2 'td' cells.")
                except Exception as cell_ex:
                     logger.error(f"Error processing cells in row {i} of the selected table: {cell_ex}")

        if not pilot_found:
            logger.warning(f"Pilot ID '{pilot_id}' was not found after checking all data rows in the second table.")
            return "ERROR: Pilot ID not found in results." # Simplified error

    except Exception as e:
        logger.error(f"Error parsing HTML or processing tables for {url}: {e}", exc_info=True)
        return f"ERROR: Could not process page data. ({e})"


# --- MODIFIED Flask Route ---
@app.route('/get_rank', methods=['GET'])
def display_rank_html():
    """
    API endpoint to get pilot rank and display it in a simple HTML page.
    Query Parameters:
        competition (str): Competition name
        task (str): Task number
        pilot_id (str): Pilot's CIVL ID
    """
    competition = request.args.get('competition')
    task = request.args.get('task')
    pilot_id = request.args.get('pilot_id')

    if not all([competition, task, pilot_id]):
        error_message = "ERROR: Missing required parameters: 'competition', 'task', 'pilot_id'"
        logger.warning(error_message)
        html_content = generate_html_page(error=error_message.replace("ERROR: ",""))
        return Response(html_content, mimetype='text/html', status=400)

    logger.info(f"Received request: competition='{competition}', task='{task}', pilot_id='{pilot_id}'")

    rank_or_error = get_pilot_rank(competition, task, pilot_id)

    status_code = 200
    if rank_or_error and rank_or_error.startswith("ERROR:"):
        logger.error(f"Error processing request: {rank_or_error}")
        # Determine status code for errors
        if "not found" in rank_or_error.lower():
            status_code = 404
        elif "Missing required parameters" in rank_or_error:
             status_code = 400
        else:
            status_code = 500
        html_content = generate_html_page(error=rank_or_error.replace("ERROR: ","")) # Pass only the message part
    elif rank_or_error: # Success
        logger.info(f"Successfully found rank: {rank_or_error}")
        html_content = generate_html_page(rank=rank_or_error)
    else:
        # Should not happen if get_pilot_rank always returns a string
        logger.error("get_pilot_rank returned None unexpectedly.")
        error_message = "An unexpected internal error occurred."
        html_content = generate_html_page(error=error_message)
        status_code = 500

    return Response(html_content, mimetype='text/html', status=status_code)


def generate_html_page(rank: str | None = None, error: str | None = None) -> str:
    """Generates a simple HTML page to display the rank or an error."""

    content = ""
    title = "Pilot Rank" # Default title

    if rank:
        content = f'<div id="rank-display">{rank}</div>'
        title = f"Rank: {rank}"
    elif error:
        content = f'<div id="error-display">{error}</div>'
        title = "Error"
    else: # Should not happen with current logic
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
        html, body {{
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: sans-serif;
            background-color: transparent;
            /* background-color: #f0f0f0; /* Optional: light background */
        }}
        body {{
            display: flex;
            justify-content: center; /* Center horizontally */
            align-items: center;     /* Center vertically */
            text-align: center;
        }}
        #rank-display {{
            font-size: 45vh; /* Very large font size relative to viewport height */
            font-weight: bold;
            color: red;
            line-height: 1; /* Adjust line height to prevent excess space */
        }}
        #error-display {{
            font-size: 5vh; /* Smaller font size for errors */
            color: #333; /* Darker color for errors */
            max-width: 80%; /* Prevent error message from being too wide */
        }}
    </style>
</head>
<body>
    {content}
</body>
</html>
    """
    return html

# --- Keep the __main__ block ---
if __name__ == '__main__':
    logger.info("Starting Flask application...")
    # Remember to set debug=False for any kind of production/stable use
    app.run(host='0.0.0.0', port=5001, debug=True)
