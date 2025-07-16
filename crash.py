import requests
import json
import os
import random
from datetime import datetime, timedelta
from atproto import Client
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable
from geopy.distance import distance
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import time # Added for time.time() - still unused, but kept as per original

# --- Configure Logging ---
import logging

# Define log file path and level
LOG_FILE = "route28_watcher.log"
# For normal operation, INFO is good. Change to logging.DEBUG for more detail in the log file.
# Console output will also follow this level.
FILE_LOG_LEVEL = logging.INFO

# Configure the root logger
logging.basicConfig(
    level=FILE_LOG_LEVEL, # Set the minimum level for messages to be processed by handlers
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE), # Send all logs to a file
        logging.StreamHandler()        # Send logs to console (stderr by default)
    ]
)

# --- Load credentials from .env file ---
load_dotenv()
BLSKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLSKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# --- Configuration Constants ---
# How long to keep crash entries in seen_crashes.json (for file size management)
# Setting this to 24 hours means any crash older than 24h will be removed from the JSON.
PURGE_THRESHOLD_HOURS = 24

# How close (km) two alerts must be to be considered the same location.
DUPLICATE_DISTANCE_KM = 0.5
# How old (minutes) an alert must be to be considered "new" if at a similar location.
# If a crash is reported again at the same spot after this time, it's treated as new.
DUPLICATE_TIME_MINUTES = 180

# --- Bounding box for Route 28 ---
ROUTE28_BOXES = [
    {
        'bottom': 40.450, 'top': 40.700, 'left': -80.050, 'right': -79.600
    }
]

# --- Setup geocoder ---
geolocator = Nominatim(user_agent="route28-crash-watcher")

# --- Helper Functions for JSON data management ---
SEEN_FILE = "seen_crashes.json"
LAST_PROMPT_FILE = "last_prompt.json"

def load_last_prompt(file_path):
    """Loads the last used prompt from a JSON file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info(f"'{file_path}' not found or empty. Starting with no last prompt.")
        return None

def save_last_prompt(prompt_text, file_path):
    """Saves the last used prompt to a JSON file."""
    try:
        with open(file_path, 'w') as f:
            json.dump(prompt_text, f) # No indent needed for a single string
    except IOError as e:
        logging.error(f"Error saving last prompt to '{file_path}': {e}")

def load_seen_data(file_path):
    """Loads existing data from a JSON file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.info(f"'{file_path}' not found. Starting with empty data.")
        return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from '{file_path}'. Starting with empty data.")
        return []

def save_seen_data(data, file_path):
    """Saves data to a JSON file."""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logging.error(f"Error saving seen data to '{file_path}': {e}")

def purge_old_crashes(seen_data_list):
    """
    Removes old crash entries from the seen_data_list based on PURGE_THRESHOLD_HOURS.
    Each crash entry must have a 'publish_datetime_utc' field.
    """
    current_time = datetime.now(ZoneInfo("UTC"))

    # Calculate the datetime threshold for purging (e.g., 24 hours ago)
    purge_cutoff_time = current_time - timedelta(hours=PURGE_THRESHOLD_HOURS)

    initial_count = len(seen_data_list)

    # Filter out old crashes based on their original publication time
    new_seen_crashes_list = []
    for crash in seen_data_list:
        try:
            crash_utc_time = datetime.strptime(crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))
            if crash_utc_time >= purge_cutoff_time:
                new_seen_crashes_list.append(crash)
        except (ValueError, KeyError):
            # If a crash entry is malformed or missing the timestamp, keep it for now
            logging.warning(f"Malformed crash entry encountered during purge: {crash}. Keeping it for now.")

    purged_count = initial_count - len(new_seen_crashes_list)
    if purged_count > 0:
        logging.info(f"Purged {purged_count} old crash entries from {SEEN_FILE}.")
    else:
        logging.info(f"No old crash entries to purge from {SEEN_FILE}.")

    return new_seen_crashes_list

def get_city_name(lat, lon):
    """Reverse geocodes coordinates to get a city name."""
    try:
        location = geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
        if location and 'address' in location.raw:
            address = location.raw['address']
            return (
                address.get('municipality') or
                address.get('city') or
                address.get('town') or
                address.get('village') or
                "unknown"
            )
    except GeocoderUnavailable:
        logging.warning("GeocoderUnavailable error when getting city name. Returning 'unknown'.")
        return "unknown"
    except Exception as e:
        logging.error(f"Unexpected error getting city name for {lat},{lon}: {e}. Returning 'unknown'.")
        return "unknown"


def is_duplicate_incident(new_alert, recent_crashes):
    """
    Checks if a new alert is a duplicate of a recently seen crash based on
    distance and time threshold.
    """
    new_location = (new_alert['latitude'], new_alert['longitude'])

    # Ensure new_alert has 'publish_datetime_utc'
    if 'publish_datetime_utc' not in new_alert:
        logging.warning("new_alert missing 'publish_datetime_utc'. Cannot check for duplicates.")
        return False # Cannot determine if duplicate without a timestamp

    new_time = datetime.strptime(new_alert['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))

    for seen_crash in recent_crashes:
        # Ensure seen_crash has required fields
        if not all(k in seen_crash for k in ['lat', 'lon', 'publish_datetime_utc']):
            logging.warning(f"Malformed seen_crash entry. Skipping: {seen_crash}")
            continue

        seen_location = (seen_crash['lat'], seen_crash['lon'])
        seen_time = datetime.strptime(seen_crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))

        # Check if the new alert's time is within the duplicate window of the seen crash's time
        time_difference = abs((new_time - seen_time).total_seconds()) / 60 # Difference in minutes

        if time_difference <= DUPLICATE_TIME_MINUTES:
            # Check if locations are close enough
            try:
                if distance(new_location, seen_location).km < DUPLICATE_DISTANCE_KM:
                    logging.info(f"Duplicate found: Near {seen_location} reported at {seen_time.astimezone(ZoneInfo('America/New_York')).strftime('%-I:%M %p')} (diff: {time_difference:.1f} min)")
                    return True
            except ValueError as e:
                logging.error(f"Error calculating distance: {e}. Locations: {new_location}, {seen_location}")
                # Treat as not a duplicate if distance calculation fails
                continue
    return False

def get_waze_alerts(box):
    """Fetches Waze alerts (accidents only) for a given bounding box."""
    url = "https://waze.p.rapidapi.com/alerts-and-jams"

    querystring = {
        "bottom_left": f"{box['bottom']},{box['left']}",
        "top_right": f"{box['top']},{box['right']}",
        "alert_types": "ACCIDENT"
    }

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "waze.p.rapidapi.com"
    }

    logging.debug(f"Querying Waze with box: {querystring}")
    try:
        resp = requests.get(url, headers=headers, params=querystring)
        resp.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        data = resp.json()
        logging.debug(f"Raw Waze response: {json.dumps(data, indent=2)}")

        # Access nested data['data']['alerts']
        return data.get("data", {}).get("alerts", [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Waze data from RapidAPI: {e}")
        return []

def format_alert(alert, last_used_prompt=None):
    """
    Formats a Waze alert into a Bluesky post message, ensuring the intro prompt doesn't repeat.
    Returns the chosen prompt and the full formatted message.
    """
    prompts = [
        "Guess what? Another crash on Route 28!",
        "Reset the 'Days Since Last Crash on Route 28' counter to zero.",
        "Route 28 is at it again. A crash has been reported.",
        "If you had 'Crash on Route 28' on your bingo card, congratulations.",
        "Oh look, a surprise Route 28 traffic jam. Kidding, it's just a crash.",
        "Sound the alarms! A crash has been spotted on Route 28.",
        "You know the drill. Another crash on Route 28.",
        "Crashy McCrash Face just entered Route 28.",
        "Just when you thought your day couldn't get more exciting, Route 28 delivers another crash.",
        "Breaking news: The asphalt on Route 28 has once again decided to engage in an unscheduled demolition derby.",
        "Feeling nostalgic for the good old days? Don't worry, Route 28 just recreated a classic crash scene for you.",
        "My therapist told me to embrace predictability. So, naturally, I looked for a crash on Route 28."
    ]

    # Create a list of available prompts, excluding the last used one if it exists
    available_prompts = [p for p in prompts if p != last_used_prompt]

    # If all prompts have been used and only one remains (which is the last_used_prompt),
    # or if the list becomes empty (shouldn't happen with at least 2 prompts),
    # fall back to choosing from the full list to avoid errors.
    if not available_prompts:
        available_prompts = prompts
        logging.warning("All prompts have been used or only last_used_prompt remains. Resetting prompt selection to full list.")

    intro = random.choice(available_prompts)
    logging.debug(f"Chosen intro: '{intro}'")

    lat = alert["latitude"]
    lon = alert["longitude"]
    # Ensure 'publish_datetime_utc' is handled robustly
    if "publish_datetime_utc" in alert:
        try:
            utc_time = datetime.strptime(alert["publish_datetime_utc"], "%Y-%m-%dT%H:%M:%S.000Z")
            local_time = utc_time.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/New_York"))
            timestamp = local_time.strftime("%-I:%M %p on %b %d")
        except ValueError:
            timestamp = "Unknown time (parse error)"
            logging.error(f"Failed to parse publish_datetime_utc: {alert.get('publish_datetime_utc')}")
    else:
        timestamp = "Unknown time"
        logging.warning("Alert missing 'publish_datetime_utc'.")

    street = alert.get("street", "an unknown street")
    city = get_city_name(lat, lon)

    Maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

    formatted_message = f"🚨 {intro}\n\n" \
                        f"📍 Location: Near {street} in {city}.\n" \
                        f"🕒 Reported at: {timestamp}\n" \
                        f"🗺  View on Map: {maps_link}\n" \
                        f"#Route28 #Pittsburgh #Traffic"

    return intro, formatted_message

def post_to_bluesky(text):
    """Posts the given text to Bluesky."""
    try:
        client = Client()
        client.login(BLSKY_HANDLE, BLSKY_APP_PASSWORD)
        client.send_post(text)
        logging.info("Successfully posted to Bluesky.")
    except Exception as e:
        logging.error(f"Error posting to Bluesky: {e}")

# --- Main Script Execution Logic ---

def check_route_28():
    # Load seen crashes at the beginning of each run
    global seen_crashes # Need to declare global to modify the list directly
    seen_crashes = load_seen_data(SEEN_FILE)

    # Load the last used prompt at the start of the run
    last_used_prompt = load_last_prompt(LAST_PROMPT_FILE)
    logging.debug(f"Loaded last used prompt: '{last_used_prompt}'")

    # Purge old crashes first to keep the seen_crashes.json manageable
    seen_crashes = purge_old_crashes(seen_crashes)
    # Save after purging, before potentially adding new entries
    save_seen_data(seen_crashes, SEEN_FILE)

    new_alerts_posted_this_run = False

    # This set will keep track of alerts we've decided to process/post in *this current run*
    # to avoid re-checking within the same batch.
    current_run_processed_alert_ids = {crash['alert_id'] for crash in seen_crashes if 'alert_id' in crash}

    for box in ROUTE28_BOXES:
        alerts = get_waze_alerts(box)
        logging.info(f"Total alerts received for this box: {len(alerts)}")

        for alert in alerts:
            # Ensure the alert has an 'alert_id' and 'publish_datetime_utc'
            alert_id = alert.get("alert_id")
            publish_time_utc = alert.get("publish_datetime_utc")

            if not alert_id or not publish_time_utc:
                logging.warning(f"Skipping alert due to missing 'alert_id' or 'publish_datetime_utc': {json.dumps(alert)}")
                continue

            logging.debug(f"Processing alert: ID={alert_id}, Type={alert.get('type')}, Street={alert.get('street')}")

            # Check if this specific alert ID has been processed in this run or previous runs
            if alert_id in current_run_processed_alert_ids:
                logging.debug(f"Skipping alert {alert_id} as it's already processed or seen.")
                continue

            # Filter for ACCIDENTs and Route 28 specific streets
            if alert.get("type") == "ACCIDENT":
                street = alert.get("street", "")
                logging.debug(f"Checking street: '{street}' for Route 28 pattern...")

                if ("28" in street and "228" not in street) and ("SR" in street or "Route" in street or "Hwy" in street or "PA" in street):
                    logging.debug(f"Street '{street}' matches Route 28 pattern.")

                    # Use your existing is_duplicate_incident logic
                    if is_duplicate_incident(alert, seen_crashes):
                        logging.info(f"Alert {alert_id} skipped due to being a recent duplicate.")
                        continue # Skip this alert, it's a duplicate

                    # If it's not a duplicate, it's a new unique crash for us to report
                    # Call format_alert, passing the last_used_prompt and getting the chosen prompt back
                    chosen_prompt, msg = format_alert(alert, last_used_prompt)
                    logging.info(f"New unique crash detected ({alert_id}). Posting to Bluesky...")
                    logging.info(f"Posting message:\n{msg}") # Added newline for better log readability

                    post_to_bluesky(msg)

                    # After successfully posting, update last_used_prompt and save it
                    last_used_prompt = chosen_prompt
                    save_last_prompt(last_used_prompt, LAST_PROMPT_FILE)
                    logging.debug(f"Saved new last used prompt: '{last_used_prompt}'")

                    # Add this alert to our "seen" list for future runs
                    # and to the current_run_processed_alert_ids set for this run.
                    seen_crashes.append({
                        "alert_id": alert_id,
                        "publish_datetime_utc": publish_time_utc,
                        "lat": alert["latitude"],
                        "lon": alert["longitude"]
                    })
                    current_run_processed_alert_ids.add(alert_id)
                    new_alerts_posted_this_run = True
                else:
                    logging.debug(f"Street '{street}' does not match Route 28 pattern for accidents. Skipping.")
            else:
                logging.debug(f"Alert {alert_id} is not an ACCIDENT type. Skipping.")

    # Save the updated seen crashes list if new alerts were posted or old ones were purged
    # We load seen data again to confirm if the file's state changed by purging
    if new_alerts_posted_this_run or len(seen_crashes) != len(load_seen_data(SEEN_FILE)):
        save_seen_data(seen_crashes, SEEN_FILE)
        logging.info(f"Updated {SEEN_FILE} with {len(seen_crashes)} entries.")
    else:
        logging.info(f"No new unique crashes found on Route 28 and no purges needed. {SEEN_FILE} remains unchanged.")


if __name__ == "__main__":
    logging.info(f"Script started at {datetime.now()}")
    if not all([BLSKY_HANDLE, BLSKY_APP_PASSWORD, RAPIDAPI_KEY]):
        logging.critical("Error: .env file is missing Bluesky or RapidAPI credentials. Please ensure all are set.")
    else:
        check_route_28()
    logging.info(f"Script finished at {datetime.now()}")
