// ==UserScript==
// @name         Download & Modify IGC Files with Custom Names
// @namespace    http://tampermonkey.net/
// @version      1.2
// @description  Adds a button to download .igc files from result tables, injecting pilot name and naming them <comp_id>-<task_id>-<#>-<pilot_name>-<id>.igc. REMEMBER TO EDIT @match!
// @author       Your Name
// @match        https://scoring.paragleiter.org/*/*.html
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @downloadURL  https://raw.githubusercontent.com/landorg/utils/refs/heads/main/scoring.js
// @updateURL  https://raw.githubusercontent.com/landorg/utils/refs/heads/main/scoring.js
// @connect      * // Necessary for GM_xmlhttpRequest to fetch from the origin serving the IGC files (use specific domain(s) if possible for security, e.g., @connect scoring.paragleiter.org)
// ==/UserScript==

(function() {
    'use strict';

    // --- Configuration ---
    // Delay in milliseconds between initiating each file *fetch* and download. Increase if hitting rate limits.
    const downloadDelay = 150; // ms - Increased delay slightly due to fetch+download steps
    // Selector for the result tables
    const tableSelector = 'table.result';
    // --- End Configuration ---

    // Helper function for delaying
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

    // Helper function to trigger download of a Blob
    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a); // Append anchor to body to ensure click works in all browsers
        a.click();
        document.body.removeChild(a); // Clean up the anchor
        // Revoke the object URL after a short delay to allow the download to start
        setTimeout(() => URL.revokeObjectURL(url), 100);
        console.log(`Download triggered for: ${filename}`);
    }


    // Function to sanitize parts of the filename
    function sanitizeFilenamePart(name) {
        if (!name) return '';
        return name.trim().replace(/\s+/g, '_').replace(/[\\/:*?"<>|]/g, '');
    }

    // Function to extract Comp ID and Task ID from URL
    function getUrlInfo(url) {
        try {
            const urlObj = new URL(url);
            const pathParts = urlObj.pathname.split('/').filter(part => part !== '');
            if (pathParts.length >= 2) {
                const compId = pathParts[pathParts.length - 2];

                const fileName = pathParts[pathParts.length - 1];
                const match = /([a-z]+)([\d]+)\.*/.exec(fileName);
                const type = match[1];
                const id = match[2];

                return {
                    compId: sanitizeFilenamePart(compId),
                    type: type,
                    id: id,
                };
            }
            console.warn("Could not reliably extract CompID and TaskID from URL path:", urlObj.pathname);
            return null;
        } catch (e) {
            console.error("Error parsing URL:", url, e);
            return null;
        }
    }

    // Function to fetch, modify, and trigger download for a single IGC file
    function fetchModifyAndDownload(url, filename, pilotName) {
        return new Promise((resolve, reject) => {
            console.log(`Fetching: ${url} for ${filename}`);
            GM_xmlhttpRequest({
                method: "GET",
                url: url,
                responseType: 'text', // Explicitly request text
                onload: function(response) {
                    if (response.status >= 200 && response.status < 300) {
                        try {
                            console.log(`Successfully fetched ${filename}. Modifying content...`);
                            let originalContent = response.responseText;
                            let lines = originalContent.split('\n');

                            // Prepare the line to insert
                            const pilotLine = `HFPLTPILOTINCHARGE:${pilotName}`; // No space after colon per IGC spec? Adjust if needed.

                            // Insert the line at index 1 (making it the second line)
                            lines.splice(1, 0, pilotLine);

                            const modifiedContent = lines.join('\n');

                            // Create a Blob from the modified content
                            // Using 'application/octet-stream' or 'text/plain' - IGC doesn't have a standard registered MIME type
                            const blob = new Blob([modifiedContent], { type: 'application/octet-stream' });

                            // Trigger the download using the helper function
                            downloadBlob(blob, filename);
                            resolve(true); // Indicate success

                        } catch (e) {
                            console.error(`Error modifying or creating blob for ${filename}:`, e);
                            reject(`Modification/Blob error for ${filename}`);
                        }
                    } else {
                        console.error(`Failed to fetch ${filename}. Status: ${response.status} ${response.statusText}`);
                        reject(`Fetch failed for ${filename} - Status ${response.status}`);
                    }
                },
                onerror: function(error) {
                    console.error(`Network error fetching ${filename}:`, error);
                    reject(`Network error for ${filename}`);
                },
                ontimeout: function() {
                     console.error(`Timeout fetching ${filename}`);
                     reject(`Timeout for ${filename}`);
                }
            });
        });
    }

    // Pause function
    async function pause() {
        window.stop();
    }
    // Main function to find links and orchestrate downloads
    async function processAndDownloadFiles(urlinfo) {
        window.stop();
        console.log("Starting IGC fetch, modify, and download process...");

        if (!urlInfo) {
            alert("Could not determine Competition ID and Task ID from the page URL. Cannot generate filenames.");
            return;
        }
        const compId = urlInfo.compId;
        const taskId = urlInfo.id;
        console.log(`Extracted CompID: ${compId}, TaskID: ${taskId}`);

        const tables = document.querySelectorAll(tableSelector);
        if (tables.length === 0) {
            alert(`No tables found matching selector: "${tableSelector}"`);
            return;
        }

        const filesToProcess = [];

        tables.forEach(table => {
            const rows = table.querySelectorAll('tbody tr.result');
            rows.forEach(row => {
                const cells = row.querySelectorAll('td.result');
                const igcLink = row.querySelector('a[href$=".igc"]');

                if (igcLink && cells.length >= 3) { // Need at least #, Id, Name
                    try {
                        const rowNum = cells[0].textContent.trim();
                        const pilotId = cells[1].textContent.trim();
                        const pilotNameRaw = cells[2].textContent.trim(); // Keep raw name for insertion

                        if (!rowNum || !pilotId || !pilotNameRaw) {
                            console.warn("Skipping row - missing data (#, ID, or Name). Row:", row);
                            return;
                        }

                        const sanitizedPilotName = sanitizeFilenamePart(pilotNameRaw);
                        const url = igcLink.href;
                        const filename = `${compId}-task${taskId}-${rowNum}-${sanitizedPilotName}-${pilotId}.igc`;

                        // Store all necessary info for processing
                        filesToProcess.push({ url, filename, pilotName: pilotNameRaw }); // Use raw name for insertion line

                    } catch (e) {
                        console.error("Error processing row data:", row, e);
                    }
                } else if (igcLink && cells.length < 3) {
                    console.warn("Found IGC link but not enough cells in row:", row);
                }
            });
        });

        if (filesToProcess.length === 0) {
            alert("No valid IGC links found in the expected table structure to process.");
            console.log("No IGC links found or data extraction failed.");
            return;
        }

        alert(`Found ${filesToProcess.length} IGC files to process and download. Starting... (Check console and download manager)`);
        console.log(`Found ${filesToProcess.length} IGC files to process:`, filesToProcess.map(f => f.filename));

        let successCount = 0;
        let failCount = 0;

        for (let i = 0; i < filesToProcess.length; i++) {
            const { url, filename, pilotName } = filesToProcess[i];
            try {
                // Await the fetch, modify, and download process for this file
                await fetchModifyAndDownload(url, filename, pilotName);
                successCount++;
            } catch (error) {
                console.error(`Failed to process ${filename}:`, error);
                failCount++;
                // Optionally, alert the user immediately on failure, or just summarize at the end.
                // alert(`Failed to process and download: ${filename}\nReason: ${error}`);
            }

            // Wait for the specified delay before starting the *next* fetch
            if (downloadDelay > 0 && i < filesToProcess.length - 1) {
                console.log(`Waiting ${downloadDelay}ms before next fetch...`);
                await sleep(downloadDelay);
            }
        }

        console.log(`Processing complete. Success: ${successCount}, Failed: ${failCount}`);
        alert(`Processing complete.\nSuccessfully downloaded: ${successCount}\nFailed: ${failCount}\n(Check browser console for details on failures)`);
    }
    const urlInfo = getUrlInfo(window.location.href);

    // --- Create and Add Button ---
    const pauseButton = document.createElement('button');
    pauseButton.textContent = '⏸'; // Updated text
    pauseButton.setAttribute('id', 'gm-pause-button'); // Updated ID
    pauseButton.setAttribute('class', 'gm-button'); // Updated ID
    pauseButton.addEventListener('click', pause);

    const downloadButton = document.createElement('button');
    downloadButton.textContent = 'Download IGCs'; // Updated text
    downloadButton.setAttribute('id', 'gm-download-modify-igc-button'); // Updated ID
    downloadButton.setAttribute('class', 'gm-button'); // Updated ID
    downloadButton.addEventListener('click', processAndDownloadFiles);

    // Style the button
    GM_addStyle(`
        #gm-download-modify-igc-button {
            background-color: #ffc107; /* Amber color for modify action */
            right: 60px;
        }
        #gm-pause-button {
            background-color: #07c1ff; /* Amber color for modify action */
        }
        .gm-button {
            position: fixed;
            top: 10px;
            right: 10px;
            z-index: 9999;
            padding: 8px 15px;
            background-color: #ffc107; /* Amber color for modify action */
            color: black;
            border: 1px solid #d39e00;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
            font-weight: bold;
        }
        #gm-download-modify-igc-button:hover {
            background-color: #e0a800;
        }
    `);

    // Add the button to the page
    if (urlInfo.type == "task") {
        document.body.appendChild(downloadButton);
    }
    document.body.appendChild(pauseButton);

})();
