# 28CrashTracker

Welcome to 28CrashTracker! This script monitors traffic incidents along specific road segments, primarily Route 28 in the Pittsburgh area, and posts updates to Bluesky. It's designed to be easily configurable for your own needs.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration (.env file)](#configuration-env-file)
- [API Services and Costs](#api-services-and-costs)
- [Running the Script](#running-the-script)
- [User Controllable Settings](#user-controllable-settings)
- [Customizing Road Segments and Bounding Box](#customizing-road-segments-and-bounding-box)
- [License](#license)
- [Contributing](#contributing)

## Features

* Monitors Waze traffic alerts for accidents.
* Focuses on configurable road names (e.g., "Route 28", "SR-28").
* Utilizes a geographical bounding box to narrow down the search area.
* Posts new and unique accident alerts to Bluesky.
* Includes retry logic for API calls to improve robustness.
* Avoids posting duplicate incidents based on proximity and time.
* Uses a history of prompts to vary post messages.
* Purges old incident data to keep the tracking efficient.
* Provides a monthly summary report of all of the crashes reported on in the script and attached a .gif of your choice from your script directory to the monthly Bluesky post.

## Installation

To get started with 28CrashTracker, you'll need Python 3 and a few libraries.

1.  **Clone the Repository:**
    First, clone this repository to your local machine:

    ```bash
    git clone https://github.com/upmcplanetracker/28crashtracker.git
    cd 28crashtracker
    ```

2.  **Install Python Dependencies:**
    It's highly recommended to use a virtual environment to manage dependencies.

    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

    * **Note:** The `crash.py` script uses `requests`, `json`, `os`, `random`, `datetime`, `atproto`, `geopy`, `dotenv`, `zoneinfo`, `time`, `logging`, and `sys`. You will need to create a `requirements.txt` file containing these dependencies if it's not already present in your repository. You can generate it by running `pip freeze > requirements.txt` after manually installing them, or just list them directly:
        ```
        requests
        atproto
        geopy
        python-dotenv
        ```
        *Self-correction: Based on the `crash.py` content, `json`, `os`, `random`, `datetime`, `zoneinfo`, `time`, `logging`, `sys` are standard library modules and do not need to be listed in `requirements.txt`.*

## Configuration (.env file)

This script uses a `.env` file for sensitive information and user-configurable settings.

### Creating the `.env` file

1.  **Create the file:** In the root directory of your cloned repository, create a new file named `.env`.

    ```bash
    sudo nano .env
    ```

2.  **Add necessary variables:** Populate the `.env` file with the variables described in the [User Controllable Settings](#user-controllable-settings) section, along with your API keys.

    Example `.env` file:

    ```
    BLUESKY_HANDLE="your_bluesky_handle.bsky.social"
    BLUESKY_APP_PASSWORD="your_bluesky_app_password"
    RAPIDAPI_KEY="YOUR_RAPIDAPI_KEY_HERE"
    OPENCAGE_API_KEY="YOUR_OPENCAGE_API_KEY_HERE"
    MONTHLY_REPORT_GIF_PATH = "your_chosen_gif_here.gif"
    ```

## API Services and Costs

This script relies on external API services, primarily through RapidAPI for Waze data, and geocoding services.

### 1. RapidAPI (Waze Alerts)

This is the primary service used to fetch traffic incident data.

1.  **Sign Up:**
    To obtain an API key, you need to sign up for an account on RapidAPI: [https://rapidapi.com/](https://rapidapi.com/)

2.  **Find the API:**
    Once signed up, search for the "Waze" API or a similar "Traffic Incident API" that provides Waze data. Subscribe to a suitable plan. The `crash.py` script uses `waze.p.rapidapi.com`.

3.  **API Key:**
    After subscribing, your API key will be available in your RapidAPI dashboard. This is the key you will place in your `.env` file under `RAPIDAPI_KEY`.

4.  **Cost:**
    The cost for API calls via RapidAPI can vary depending on the provider and plan. A common pricing model is approximately **$25 for 10,000 API calls**. Please verify the exact pricing on the RapidAPI platform for the specific API you are using, as this can change.

### 2. OpenCage Geocoding (Optional, but Recommended Failover)

This service is used as a failover for reverse geocoding (converting coordinates to a city name) if Nominatim fails.

1.  **Sign Up:**
    Visit the OpenCage Data website: [https://opencagedata.com/](https://opencagedata.com/) and sign up for an account.

2.  **API Key:**
    After signing up, you will find your API key in your OpenCage dashboard. Add this key to your `.env` file as `OPENCAGE_API_KEY`.
    *Note: If `OPENCAGE_API_KEY` is not provided in your `.env` file, the script will log a warning, and OpenCage geocoding will not be available as a failover.*

## Running the Script

The script is designed to be run periodically to check for new incidents. A common way to automate this on Linux/macOS systems is using `cron`.

### Running with `crontab`

1.  **Open Crontab Editor:**
    Open your crontab file for editing:

    ```bash
    crontab -e
    ```

2.  **Add a Cron Job:**
    Add a line to your crontab file to execute the script every 10 minutes. This frequency should help you stay under the 10,000 API calls per month limit (10,000 calls / (30 days * 24 hours * 6 calls/hour) $\approx$ 5.7 minutes per call, so 10 minutes is a safe interval).

    ```cron
    */10 * * * * /usr/bin/python3 /path/to/your/28crashtracker/crash.py >> /path/to/your/28crashtracker/cron.log 2>&1
    ```

    **Important:**
    * Replace `/usr/bin/python3` with the absolute path to your Python interpreter (you can find this by running `which python3` or `where python3` in your virtual environment if you activated it, or the system-wide path).
    * Replace `/path/to/your/28crashtracker/crash.py` with the absolute path to your script's main entry point (in this case, `crash.py`).
    * The `>> /path/to/your/28crashtracker/cron.log 2>&1` part redirects all output (stdout and stderr) to a log file, which is helpful for debugging. The script also writes to `route28_watcher.log`.

3.  **Save and Exit:**
    Save the crontab file and exit the editor. The cron job will now be scheduled.

## User Controllable Settings

These settings can be modified in your `.env` file to customize the script's behavior.

* **`BLUESKY_HANDLE`**: Your Bluesky handle (e.g., `your_name.bsky.social`).
    * **What it does:** Used to log into your Bluesky account for posting.
    * **How to change:** Set to your Bluesky handle.

* **`BLUESKY_APP_PASSWORD`**: Your Bluesky app password. **(Highly Recommended: Do NOT use your main account password)**
    * **What it does:** Used to authenticate your Bluesky client.
    * **How to change:** Generate an app password from your Bluesky settings and set it here.

* **`RAPIDAPI_KEY`**: Your API key obtained from RapidAPI for the Waze alerts.
    * **What it does:** Authenticates your requests to the RapidAPI Waze service.
    * **How to change:** Replace `"YOUR_RAPIDAPI_KEY_HERE"` with your actual API key.

* **`OPENCAGE_API_KEY`**: Your API key obtained from OpenCage Data for geocoding failover.
    * **What it does:** Provides a fallback geocoding service if Nominatim fails to resolve coordinates to a city name.
    * **How to change:** Replace `"YOUR_OPENCAGE_API_KEY_HERE"` with your actual API key. (Optional, but recommended)

* **`PURGE_THRESHOLD_HOURS`** (Internal constant in `crash.py`): The age in hours after which old crash entries are purged from the `seen_crashes.json` file.
    * **What it does:** Helps keep the `seen_crashes.json` file from growing indefinitely and prevents redundant duplicate checks on very old incidents.
    * **How to change:** Modify the `PURGE_THRESHOLD_HOURS` variable directly in `crash.py`. Default is `24` hours.

* **`DUPLICATE_DISTANCE_KM`** (Internal constant in `crash.py`): The maximum distance in kilometers for two incidents to be considered duplicates.
    * **What it does:** Prevents the script from posting multiple times about the same incident if reports come in from slightly different coordinates.
    * **How to change:** Modify the `DUPLICATE_DISTANCE_KM` variable directly in `crash.py`. Default is `1` km.

* **`DUPLICATE_TIME_MINUTES`** (Internal constant in `crash.py`): The maximum time difference in minutes for two incidents to be considered duplicates.
    * **What it does:** Works with `DUPLICATE_DISTANCE_KM` to define what constitutes a duplicate incident. An incident is a duplicate if it's within this time window *and* within the distance threshold of a previously seen incident.
    * **How to change:** Modify the `DUPLICATE_TIME_MINUTES` variable directly in `crash.py`. Default is `45` minutes.

* **`MAX_WAZE_API_RETRIES`** (Internal constant in `crash.py`): Maximum number of retries for Waze API calls in case of temporary failures.
    * **What it does:** Improves script robustness by retrying failed API requests with exponential backoff.
    * **How to change:** Modify the `MAX_WAZE_API_RETRIES` variable directly in `crash.py`. Default is `4` retries.

* **`MAX_RECENT_PROMPTS`** (Internal constant in `crash.py`): The number of recently used introductory prompts to avoid.
    * **What it does:** Ensures that the script cycles through a variety of opening phrases for new posts, preventing repetitive messaging.
    * **How to change:** Modify the `MAX_RECENT_PROMPTS` variable directly in `crash.py`. Default is `12`.

## Customizing Road Segments and Bounding Box

The script is currently hardcoded to monitor specific roads and geographical areas relevant to Route 28 in Pittsburgh. If you wish to adapt this script for different roads or regions, you'll need to adjust two key areas directly within `crash.py`:

1.  **`ROUTE28_BOXES` coordinates:**
    This variable defines the geographical bounding box (or boxes) where the script will search for incidents. The current values are:

    ```python
    ROUTE28_BOXES = [
        {
            'bottom': 40.450, 'top': 40.700, 'left': -80.050, 'right': -79.600
        }
    ]
    ```
    * **How to change:**
        * Edit the `ROUTE28_BOXES` list in `crash.py`. You can define multiple bounding boxes if your target area is not contiguous.
        * Each dictionary in the list should contain `bottom` (min latitude), `top` (max latitude), `left` (min longitude), and `right` (max longitude).
        * You can use online tools like [bboxfinder.com](https://bboxfinder.com/) to easily determine the latitude and longitude coordinates for your desired region.

2.  **Road Name Filtering Logic:**
    The script filters alerts to find incidents on "Route 28". The relevant lines are in the `check_route_28` function:

    ```python
    if ("28" in street and "228" not in street) and ("SR" in street or "Route" in street or "Hwy" in street or "PA" in street):
    ```
    * **How to change:**
        * Modify this `if` statement to match the road names you are interested in.
        * For example, if you want to track "SR-79" and "I-376", you might change it to:
            ```python
            if ("SR-79" in street or "I-376" in street):
            ```
        * Ensure that the road names you specify here accurately reflect how they appear in the data provided by the Waze API.

## License

The license for this project can be found on my GitHub page at [LICENSE](https://github.com/upmcplanetracker/28crashtracker/blob/main/LICENSE).

## Contributing

Contributions are welcome! If you have suggestions for improvements, bug fixes, or new features, please open an issue or submit a pull request on the [GitHub repository](https://github.com/upmcplanetracker/28crashtracker).  API calls cost money.  [Buy me a coffee](https://buymeacoffee.com/pghcrash).
