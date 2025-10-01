# Pittsburgh Combined Crash Watcher

Welcome! This script monitors traffic incidents along multiple, configurable road systems in the Pittsburgh area, specifically Route 28 and the Parkway East. It classifies incidents by road and posts distinct updates to dedicated Bluesky accounts for each.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration (.env file)](#configuration-env-file)
- [API Services and Costs](#api-services-and-costs)
- [Running the Script](#running-the-script)
- [User Controllable Settings](#user-controllable-settings)
- [Customizing for New Roads](#customizing-for-new-roads)
- [License](#license)
- [Contributing](#contributing)

## Features

* Monitors a combined geographical area for Waze traffic alerts.
* Classifies accidents to specific roadways (e.g., "Route 28", "Parkway East") using regular expressions.
* Posts new and unique accident alerts to **separate, dedicated Bluesky accounts** for each road.
* Includes retry logic for API calls to improve robustness.
* Avoids posting duplicate incidents based on proximity and time.
* Uses a unique history of prompts for each road to vary post messages.
* Purges old incident data to keep tracking efficient.
* Generates and posts **separate monthly summary reports** for each monitored road, with an optional unique GIF attached to each.

## Installation

To get started, you'll need Python 3 and a few libraries.

1.  **Clone the Repository:**
    First, clone this repository to your local machine:
    ```bash
    git clone https://github.com/upmcplanetracker/28crashtracker.git
    cd 28crashtracker
    ```

2.  **Install Python Dependencies:**
    It's highly recommended to use a virtual environment.
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```
    If a `requirements.txt` file is not available, you can create one with the following content and then run `pip install -r requirements.txt`:
    ```
    requests
    atproto
    geopy
    python-dotenv
    ```

## Configuration (.env file)

This script uses a single `.env` file to manage credentials and settings for all monitored roads.

1.  **Create the file:** In the root directory of your project, create a new file named `.env`.
    ```bash
    sudo nano .env
    ```

2.  **Add necessary variables:** Populate the `.env` file with the variables for **each** road system you are tracking, along with your general API keys.

    **Example `.env` file for Route 28 and Parkway East:**
    ```
    # --- Bluesky Credentials for Route 28 ---
    BLUESKY_HANDLE_ROUTE28="your_route28_handle.bsky.social"
    BLUESKY_APP_PASSWORD_ROUTE28="your_route28_app_password"
    MONTHLY_STATS_GIF_ROUTE28="path/to/your/route28.gif"

    # --- Bluesky Credentials for Parkway East ---
    BLUESKY_HANDLE_PARKWAYEAST="your_parkway_handle.bsky.social"
    BLUESKY_APP_PASSWORD_PARKWAYEAST="your_parkway_app_password"
    MONTHLY_STATS_GIF_PARKWAYEAST="path/to/your/parkway.gif"

    # --- General API Keys ---
    RAPIDAPI_KEY="YOUR_RAPIDAPI_KEY_HERE"
    OPENCAGE_API_KEY="YOUR_OPENCAGE_API_KEY_HERE"
    ```

## API Services and Costs

This script relies on external API services for traffic and location data.

### 1. RapidAPI (Waze Alerts)

This is the primary service used to fetch traffic data.

1.  **Sign Up:** Create an account on [RapidAPI](https://rapidapi.com/).
2.  **Find the API:** Search for the "Waze" API on the platform. The script is configured for the endpoint `waze.p.rapidapi.com`. Subscribe to a suitable plan.
3.  **API Key:** Your API key will be available in your RapidAPI dashboard. Place this in your `.env` file as `RAPIDAPI_KEY`.
4.  **Cost:** Pricing can vary. A common plan is approximately **$25 for 10,000 API calls**. Please verify the current pricing on the RapidAPI platform.

### 2. OpenCage Geocoding (Optional, but Recommended)

This is a fallback service for converting coordinates to a city name if the primary service (Nominatim) fails.

1.  **Sign Up:** Visit the [OpenCage Data website](https://opencagedata.com/) and sign up for an account.
2.  **API Key:** Find your API key in your OpenCage dashboard. Add this key to your `.env` file as `OPENCAGE_API_KEY`. If this key is not provided, the script will still run but without the geocoding failover capability.

## Running the Script

The script is intended to be run periodically. Using `cron` on Linux/macOS is an effective way to automate this.

1.  **Open Crontab Editor:**
    ```bash
    crontab -e
    ```

2.  **Add a Cron Job:**
    Add a line to execute the script at your desired frequency. Running it every 10 minutes is a safe interval to stay within a 10,000 calls/month limit.

    ```cron
    */10 * * * * /path/to/your/venv/bin/python3 /path/to/your/28crashtracker/combinedcrash.py >> /path/to/your/28crashtracker/cron.log 2>&1
    ```

    **Important:**
    * Replace `/path/to/your/venv/bin/python3` with the absolute path to the Python interpreter **inside your virtual environment**.
    * Replace `/path/to/your/28crashtracker/combinedcrash.py` with the absolute path to the script.
    * The `>> ...` portion redirects all output to a log file for debugging. The script also writes to `combined_crash_watcher.log` by default.

## User Controllable Settings

### Settings in `.env` file:

* **`BLUESKY_HANDLE_[ROAD]`**: Your Bluesky handle for a specific road (e.g., `BLUESKY_HANDLE_ROUTE28`).
* **`BLUESKY_APP_PASSWORD_[ROAD]`**: The Bluesky app password for that account. **(Do NOT use your main password)**.
* **`MONTHLY_REPORT_GIF_PATH_[ROAD]`**: The local file path to a GIF you want to attach to the monthly report for that road.
* **`RAPIDAPI_KEY`**: Your API key for the Waze service on RapidAPI.
* **`OPENCAGE_API_KEY`**: Your optional API key from OpenCage Data for geocoding failover.

### Settings inside `combinedcrash.py`:

These constants can be modified directly within the script for fine-tuning.

* `PURGE_THRESHOLD_HOURS`: How long (in hours) to keep a crash in the `seen_crashes` file before purging. Default: `24`.
* `DUPLICATE_DISTANCE_KM`: Maximum distance (in km) between two incidents to be considered a duplicate. Default: `1`.
* `DUPLICATE_TIME_MINUTES`: Maximum time difference (in minutes) for two incidents to be considered a duplicate. Default: `45`.
* `MAX_WAZE_API_RETRIES`: Number of times to retry fetching from the Waze API on failure. Default: `4`.
* `MAX_RECENT_PROMPTS`: How many recent post openings to remember to avoid repetition for each bot. Default: `12`.

## Customizing for New Roads

To adapt the script to monitor new roads or regions, you'll need to modify `combinedcrash.py` in three places:

1.  **Define a Combined Bounding Box:**
    Adjust the `COMBINED_BOUNDING_BOX` dictionary to encompass all geographic areas you want to monitor.
    ```python
    COMBINED_BOUNDING_BOX = {
        'bottom': 40.400, 'top': 40.750, 'left': -80.300, 'right': -79.550
    }
    ```
    You can use an online tool like [bboxfinder.com](https://bboxfinder.com/) to find the coordinates for your desired region.

2.  **Update the `classify_alert_by_road` function:**
    Add logic to this function to recognize your new road from the street name provided by the Waze API. Use `re.search` for flexible pattern matching.
    ```python
    def classify_alert_by_road(alert):
        street = alert.get("street") or ""
        # ... existing logic for Route 28 and Parkway East
        
        # Add your new logic here
        if re.search(r'\b(I-79|INTERSTATE 79)\b', street, re.IGNORECASE):
            return "INTERSTATE79"
            
        return "UNKNOWN"
    ```

3.  **Add a Configuration Entry to `FILE_PATHS`:**
    Add a new key-value pair to the `FILE_PATHS` dictionary for your new road. The key must match the string you return from `classify_alert_by_road` (e.g., `"INTERSTATE79"`).
    ```python
    FILE_PATHS = {
        "ROUTE28": { ... },
        "PARKWAYEAST": { ... },
        "INTERSTATE79": {
            "SEEN_FILE": "seen_crashes_i79.json",
            "LAST_PROMPTS_FILE": "last_prompts_i79.json",
            "MONTHLY_CRASH_FILE": "monthly_crash_data_i79.json",
            "BLUESKY_HANDLE": os.getenv("BLUESKY_HANDLE_I79"),
            "BLUESKY_APP_PASSWORD": os.getenv("BLUESKY_APP_PASSWORD_I79"),
            "MONTHLY_REPORT_GIF_PATH": os.getenv("MONTHLY_STATS_GIF_I79"),
            "PROMPTS": ["Oh boy, a crash on I-79...", "Another one on I-79."],
            "REPORT_MESSAGE_TEMPLATE": (
                "🚗 Monthly Crash Report for {reported_month_name} {reported_year}:\n"
                "There were {total_crashes_last_month} car crashes on I-79.\n"
                "#Pittsburgh #Traffic #I79"
            ),
            "EMOJIS": {"intro": "💥", "location": "📍", "reported_at": "⌚"}
        }
    }
    ```
    Finally, remember to add the corresponding `BLUESKY_HANDLE_I79`, `BLUESKY_APP_PASSWORD_I79`, and `MONTHLY_STATS_GIF_I79` variables to your `.env` file.

## License

The license for this project can be found on my GitHub page at [LICENSE](https://github.com/upmcplanetracker/28crashtracker/blob/main/LICENSE).

## Contributing

Contributions are welcome! If you have suggestions, bug fixes, or new features, please open an issue or submit a pull request on the [GitHub repository](https://github.com/upmcplanetracker/28crashtracker). API calls cost money. [Buy me a coffee](https://buymeacoffee.com/pghcrash).
