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
import time # Added for time.time()

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
# Your request was "if a new crash takes place at the same place 3 hours later", so 3 * 60 = 180 minutes.
# You said "prune old ones every 2 hours" earlier, but that refers to file management, not re-posting.
# For re-posting a crash at the same location as "new", use this value.
# I'm setting this to 180 minutes (3 hours) based on your last comment.
DUPLICATE_TIME_MINUTES = 180

# --- Setup geocoder ---
geolocator = Nominatim(user_agent="route28-crash-watcher")

# --- Helper Functions for JSON data management ---
SEEN_FILE = "seen_crashes.json"

def load_seen_data(file_path):
    """Loads existing data from a JSON file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"'{file_path}' not found. Starting with empty data.")
        return [] # Your seen_crashes is a list, not a dict with a 'crashes' key
    except json.JSONDecodeError:
        print(f"Error decoding JSON from '{file_path}'. Starting with empty data.")
        return [] # Your seen_crashes is a list

def save_seen_data(data, file_path):
    """Saves data to a JSON file."""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2) # Use indent for readability, your original used 2

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
            # or log a warning if you want to clean up bad entries.
            new_seen_crashes_list.append(crash)
            print(f"Warning: Malformed crash entry encountered during purge: {crash}")


    purged_count = initial_count - len(new_seen_crashes_list)
    if purged_count > 0:
        print(f"Purged {purged_count} old crash entries from {SEEN_FILE}.")
    else:
        print(f"No old crash entries to purge from {SEEN_FILE}.")

    return new_seen_crashes_list


# --- Existing Functions (retained and potentially adapted) ---

def get_city_name(lat, lon):
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
        return "unknown"
    return "unknown"

# --- Bounding box for Route 28 ---
ROUTE28_BOXES = [
    {
        'bottom': 40.450, 'top': 40.700, 'left': -80.050, 'right': -79.600
    }
]

# NO LONGER NEEDED HERE: seen_crashes will be loaded by load_seen_data in main logic
# if os.path.exists(SEEN_FILE):
#     with open(SEEN_FILE, "r") as f:
#         try:
#             seen_crashes = json.load(f)
#         except json.JSONDecodeError:
#             seen_crashes = []
# else:
#     seen_crashes = []

def is_duplicate_incident(new_alert, recent_crashes):
    """
    Checks if a new alert is a duplicate of a recently seen crash based on
    distance and time threshold.
    """
    new_location = (new_alert['latitude'], new_alert['longitude'])

    # Ensure new_alert has 'publish_datetime_utc'
    if 'publish_datetime_utc' not in new_alert:
        print("Warning: new_alert missing 'publish_datetime_utc'. Cannot check for duplicates.")
        return False # Cannot determine if duplicate without a timestamp

    new_time = datetime.strptime(new_alert['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))

    for seen_crash in recent_crashes:
        # Ensure seen_crash has required fields
        if not all(k in seen_crash for k in ['lat', 'lon', 'publish_datetime_utc']):
            print(f"Warning: Malformed seen_crash entry. Skipping: {seen_crash}")
            continue

        seen_location = (seen_crash['lat'], seen_crash['lon'])
        seen_time = datetime.strptime(seen_crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))

        # Check if the new alert's time is within the duplicate window of the seen crash's time
        # We check both directions: new_time relative to seen_time, and seen_time relative to new_time
        time_difference = abs((new_time - seen_time).total_seconds()) / 60 # Difference in minutes

        if time_difference <= DUPLICATE_TIME_MINUTES:
            # Check if locations are close enough
            try:
                if distance(new_location, seen_location).km < DUPLICATE_DISTANCE_KM:
                    print(f"Duplicate found: Near {seen_location} reported at {seen_time.astimezone(ZoneInfo('America/New_York')).strftime('%-I:%M %p')} (diff: {time_difference:.1f} min)")
                    return True
            except ValueError as e:
                print(f"Error calculating distance: {e}. Locations: {new_location}, {seen_location}")
                # Treat as not a duplicate if distance calculation fails
                continue
    return False

def get_waze_alerts(box):
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

    print(f"Querying Waze with box: {querystring}")
    try:
        resp = requests.get(url, headers=headers, params=querystring)
        resp.raise_for_status()
        data = resp.json()
        print(f"Raw Waze response: {json.dumps(data, indent=2)}")

        # Access nested data['data']['alerts']
        return data.get("data", {}).get("alerts", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Waze data from RapidAPI: {e}")
        return []

def format_alert(alert):
    prompts = [
        "Guess what? Another crash on Route 28!",
        "Reset the 'Days Since Last Crash on Route 28' counter to zero.",
        "Route 28 is at it again. A crash has been reported.",
        "If you had 'crash on Route 28' on your bingo card, congratulations.",
        "Oh look, a surprise Route 28 traffic jam. Kidding, it's just a crash.",
        "Sound the alarms! A crash has been spotted on Route 28.",
        "You know the drill. Another crash on Route 28.",
        "Crashy McCrash Face just entered Route 28."
    ]

    intro = random.choice(prompts)

    lat = alert["latitude"]
    lon = alert["longitude"]
    # Ensure 'publish_datetime_utc' is handled robustly
    if "publish_datetime_utc" in alert:
        utc_time = datetime.strptime(alert["publish_datetime_utc"], "%Y-%m-%dT%H:%M:%S.000Z")
        local_time = utc_time.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/New_York"))
        timestamp = local_time.strftime("%-I:%M %p on %b %d")
    else:
        timestamp = "Unknown time"
        print("Warning: Alert missing 'publish_datetime_utc'.")

    street = alert.get("street", "an unknown street")
    city = get_city_name(lat, lon)

    return f"🚨 {intro}\n\n" \
           f"📍 Location: Near {street} in {city}.\n" \
           f"🕒 Reported at: {timestamp}\n" \
           f"#Route28 #Pittsburgh #Traffic"

def post_to_bluesky(text):
    try:
        client = Client()
        client.login(BLSKY_HANDLE, BLSKY_APP_PASSWORD)
        client.send_post(text)
        print("Successfully posted to Bluesky.")
    except Exception as e:
        print(f"Error posting to Bluesky: {e}")

# --- Main Script Execution Logic ---

def check_route_28():
    # Load seen crashes at the beginning of each run
    global seen_crashes # Need to declare global to modify the list directly
    seen_crashes = load_seen_data(SEEN_FILE)

    # Purge old crashes first to keep the seen_crashes.json manageable
    seen_crashes = purge_old_crashes(seen_crashes)

    new_alerts_posted_this_run = False

    # This set will keep track of alerts we've decided to process/post in *this current run*
    # to avoid re-checking within the same batch.
    current_run_processed_alert_ids = {crash['alert_id'] for crash in seen_crashes if 'alert_id' in crash}


    for box in ROUTE28_BOXES:
        alerts = get_waze_alerts(box)
        print(f"Total alerts received for this box: {len(alerts)}")

        for alert in alerts:
            # Ensure the alert has an 'alert_id' and 'publish_datetime_utc'
            alert_id = alert.get("alert_id")
            publish_time_utc = alert.get("publish_datetime_utc")

            if not alert_id or not publish_time_utc:
                print(f"Skipping alert due to missing 'alert_id' or 'publish_datetime_utc': {json.dumps(alert)}")
                continue

            print(f"DEBUG: Processing alert: ID={alert_id}, Type={alert.get('type')}, Street={alert.get('street')}")

            # Check if this specific alert ID has been processed in this run or previous runs
            if alert_id in current_run_processed_alert_ids:
                print(f"Skipping alert {alert_id} as it's already processed or seen.")
                continue

            # Filter for ACCIDENTs and Route 28 specific streets
            if alert.get("type") == "ACCIDENT":
                street = alert.get("street", "")
                print(f"Checking street: '{street}' for Route 28 pattern...")

                if "28" in street and ("SR" in street or "Route" in street or "Hwy" in street or "PA" in street):
                    print(f"Street '{street}' matches Route 28 pattern.")

                    # Use your existing is_duplicate_incident logic
                    if is_duplicate_incident(alert, seen_crashes):
                        print(f"Alert {alert_id} skipped due to being a recent duplicate.")
                        continue # Skip this alert, it's a duplicate

                    # If it's not a duplicate, it's a new unique crash for us to report
                    msg = format_alert(alert)
                    print(f"New unique crash detected ({alert_id}). Posting to Bluesky...")
                    print(msg)
                    post_to_bluesky(msg)

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
                    print(f"Street '{street}' does not match Route 28 pattern for accidents.")
            else:
                print(f"Alert {alert_id} is not an ACCIDENT type.")

    # Save the updated seen crashes list AFTER processing all alerts for all boxes
    if new_alerts_posted_this_run or len(seen_crashes) != len(load_seen_data(SEEN_FILE)):
        # Only save if something new was posted OR if old entries were purged
        save_seen_data(seen_crashes, SEEN_FILE)
        print(f"Updated {SEEN_FILE} with {len(seen_crashes)} entries.")
    else:
        print(f"No new unique crashes found on Route 28 and no purges needed. {SEEN_FILE} remains unchanged.")


if __name__ == "__main__":
    print(f"Script started at {datetime.now()}")
    if not all([BLSKY_HANDLE, BLSKY_APP_PASSWORD, RAPIDAPI_KEY]):
        print("Error: .env file is missing Bluesky or RapidAPI credentials. Please ensure all are set.")
    else:
        check_route_28()
    print(f"Script finished at {datetime.now()}")
