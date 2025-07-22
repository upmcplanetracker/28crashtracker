# -*- coding: utf-8 -*-

import requests
import json
import os
import random
from datetime import datetime, timedelta
from atproto import Client, models  # Import models to access the embed types
from geopy.geocoders import Nominatim, OpenCage
from geopy.exc import GeocoderUnavailable
from geopy.distance import distance
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import time
import logging
import sys

# --- Configure Logging ---
LOG_FILE = "route28_watcher.log"
FILE_LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=FILE_LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# --- Load credentials from .env file ---
load_dotenv()
BLSKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLSKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY") # Add this line

# --- Configuration Constants ---
PURGE_THRESHOLD_HOURS = 24
DUPLICATE_DISTANCE_KM = 1
DUPLICATE_TIME_MINUTES = 45
MAX_WAZE_API_RETRIES = 4 # Maximum number of retries for Waze API calls
MAX_RECENT_PROMPTS = 12  # Number of recent prompts to track
# --- Bounding box for Route 28 ---
ROUTE28_BOXES = [
    {
        'bottom': 40.450, 'top': 40.700, 'left': -80.050, 'right': -79.600
    }
]

# --- Setup geocoder ---
geolocator = Nominatim(user_agent="route28-crash-watcher")
opencage_geolocator = None # Initialize as None
if OPENCAGE_API_KEY: # Only initialize if key is present
    opencage_geolocator = OpenCage(api_key=OPENCAGE_API_KEY, user_agent="route28-crash-watcher-opencage")
else:
    logging.warning("OPENCAGE_API_KEY not found in .env. OpenCage geocoding failover will not be available.")

# --- Helper Functions ---
SEEN_FILE = "seen_crashes.json"
LAST_PROMPTS_FILE = "last_prompts_route28.json" # Changed filename to reflect multiple prompts

def load_last_prompts(file_path): # New function
    """Load the list of recently used prompts""" # New function
    try: # New function
        with open(file_path, 'r') as f: # New function
            data = json.load(f) # New function
            # Ensure we have a list (backwards compatibility for old single prompt file) # New function
            if isinstance(data, str): # New function
                return [data]  # Convert old single prompt to list # New function
            elif isinstance(data, list): # New function
                return data # New function
            else: # New function
                logging.warning(f"Unexpected data format in '{file_path}'. Starting with empty list.") # New function
                return [] # New function
    except (FileNotFoundError, json.JSONDecodeError): # New function
        logging.info(f"'{file_path}' not found or empty. Starting with no recent prompts.") # New function
        return [] # New function
    except IOError as e: # Add this block
        logging.critical(f"Permission error or other I/O error reading '{file_path}': {e}. Cannot load recent prompts.")
        # Decide if you want to exit here or return empty and continue with a warning
        return []

def save_last_prompts(prompts_list, file_path): # New function
    """Save the list of recently used prompts""" # New function
    try: # New function
        with open(file_path, 'w') as f: # New function
            json.dump(prompts_list, f, indent=2) # New function
    except IOError as e: # New function
        logging.error(f"Error saving recent prompts to '{file_path}': {e}") # New function

def add_prompt_to_history(new_prompt, prompts_list, max_prompts=MAX_RECENT_PROMPTS): # New function
    """Add a new prompt to the history and maintain the maximum count""" # New function
    # Remove the prompt if it already exists to avoid duplicates and bring it to front # New function
    if new_prompt in prompts_list: # New function
        prompts_list.remove(new_prompt) # New function
    
    # Add the new prompt to the beginning # New function
    prompts_list.insert(0, new_prompt) # New function
    
    # Keep only the most recent prompts # New function
    return prompts_list[:max_prompts] # New function

def load_seen_data(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.info(f"'{file_path}' not found. Starting with empty data.")
        return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from '{file_path}'. Starting with empty data.")
        return []
    except IOError as e: # Add this block
        logging.critical(f"Permission error or other I/O error reading '{file_path}': {e}. Cannot load seen data.")
        # Decide if you want to exit here or return empty and continue with a warning
        return []

def save_seen_data(data, file_path):
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logging.error(f"Error saving seen data to '{file_path}': {e}")

def purge_old_crashes(seen_data_list):
    current_time = datetime.now(ZoneInfo("UTC"))
    purge_cutoff_time = current_time - timedelta(hours=PURGE_THRESHOLD_HOURS)
    initial_count = len(seen_data_list)
    new_seen_crashes_list = []
    for crash in seen_data_list:
        try:
            # Ensure the timestamp is correctly parsed with .000Z
            crash_utc_time = datetime.strptime(crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=ZoneInfo("UTC"))
            if crash_utc_time >= purge_cutoff_time:
                new_seen_crashes_list.append(crash)
        except (ValueError, KeyError) as e:
            logging.warning(f"Malformed crash entry encountered during purge: {crash}. Error: {e}. Skipping this entry.")
            # Do not append malformed entries, but log the warning.
            continue
    purged_count = initial_count - len(new_seen_crashes_list)
    if purged_count > 0:
        logging.info(f"Purged {purged_count} old crash entries from {SEEN_FILE}.")
    else:
        logging.info(f"No old crash entries to purge from {SEEN_FILE}.")
    return new_seen_crashes_list

def get_city_name(lat, lon):
    city = "unknown" # Default city if nothing found

    # --- Attempt 1: Nominatim ---
    try:
        logging.debug(f"Attempting Nominatim for {lat},{lon}")
        location = geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
        if location and 'address' in location.raw:
            address = location.raw['address']
            city = (
                address.get('municipality') or
                address.get('city') or
                address.get('town') or
                address.get('village')
            )
            if city: # If a city was found by Nominatim, return it
                return city
    except GeocoderUnavailable:
        logging.warning("Nominatim GeocoderUnavailable. Falling back to OpenCage.")
    except Exception as e:
        logging.warning(f"Nominatim lookup failed unexpectedly for {lat},{lon}: {e}. Falling back to OpenCage.")

    # --- Attempt 2: OpenCage (Failover) ---
    if opencage_geolocator: # Only try if OpenCage was initialized with a key
        try:
            logging.debug(f"Attempting OpenCage for {lat},{lon}")
            location_opencage = opencage_geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
            if location_opencage and 'address' in location_opencage.raw:
                address_opencage = location_opencage.raw['address']
                city = (
                    address_opencage.get('municipality') or
                    address_opencage.get('city') or
                    address_opencage.get('town') or
                    address_opencage.get('village')
                )
                if city: # If a city was found by OpenCage, return it
                    logging.info(f"Successfully retrieved city from OpenCage for {lat},{lon}.")
                    return city
        except Exception as e:
            logging.error(f"OpenCage geocoding failed for {lat},{lon}: {e}.")
    else:
        logging.debug("OpenCage geolocator not initialized (API key missing or failed init).")

    logging.warning(f"Could not determine city name for {lat},{lon} using any geocoder.")
    return "unknown" # Return "unknown" if both fail

def is_duplicate_incident(new_alert, recent_crashes):
    new_location = (new_alert['latitude'], new_alert['longitude'])
    if 'publish_datetime_utc' not in new_alert:
        logging.warning("new_alert missing 'publish_datetime_utc'. Cannot check for duplicates.")
        return False
    # Use .%fZ for robustness with Waze timestamps
    new_time = datetime.strptime(new_alert['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=ZoneInfo("UTC"))
    
    for seen_crash in recent_crashes:
        if not all(k in seen_crash for k in ['lat', 'lon', 'publish_datetime_utc']):
            logging.warning(f"Malformed seen_crash entry. Skipping: {seen_crash}")
            continue
        seen_location = (seen_crash['lat'], seen_crash['lon'])
        # Use .%fZ for robustness with Waze timestamps
        seen_time = datetime.strptime(seen_crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=ZoneInfo("UTC"))
        time_difference = abs((new_time - seen_time).total_seconds()) / 60
        if time_difference <= DUPLICATE_TIME_MINUTES:
            try:
                if distance(new_location, seen_location).km < DUPLICATE_DISTANCE_KM:
                    logging.info(f"Duplicate found: Near {seen_location} reported at {seen_time.astimezone(ZoneInfo('America/New_York')).strftime('%-I:%M %p')} (diff: {time_difference:.1f} min)")
                    return True
            except ValueError as e:
                logging.error(f"Error calculating distance: {e}. Locations: {new_location}, {seen_location}")
                continue
    return False

def get_waze_alerts(box):
    """
    Fetches Waze alerts from RapidAPI with retry logic.
    Retries up to MAX_WAZE_API_RETRIES times with exponential backoff.
    """
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

    for attempt in range(MAX_WAZE_API_RETRIES + 1): # +1 for the initial attempt
        logging.debug(f"Attempt {attempt + 1}/{MAX_WAZE_API_RETRIES + 1} to query Waze with box: {querystring}")
        try:
            resp = requests.get(url, headers=headers, params=querystring, timeout=30)
            resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            logging.info(f"Accessed Waze successfully on try #{attempt + 1}.")
            data = resp.json()
            return data.get("data", {}).get("alerts", [])
        except requests.exceptions.RequestException as e:
            if attempt < MAX_WAZE_API_RETRIES:
                wait_time = 2 ** attempt # Exponential backoff: 1s, 2s, 4s, 8s, etc.
                logging.warning(f"Error fetching Waze data from RapidAPI (attempt {attempt + 1}/{MAX_WAZE_API_RETRIES + 1}): {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"Failed to fetch Waze data after {MAX_WAZE_API_RETRIES + 1} attempts. Final error: {e}")
                return [] # Return empty list on final failure

def format_alert(alert, recent_prompts=None): # Modified function signature
    """Format alert with prompt selection that avoids recently used prompts""" # Modified docstring
    if recent_prompts is None: # New logic
        recent_prompts = [] # New logic

    prompts = [
        "Guess what? Another crash on Route 28!", "Reset the 'Days Since Last Crash on Route 28' counter to zero.", "Route 28 is at it again. A crash has been reported.", "If you had 'Crash on Route 28' on your bingo card, congratulations.", "Oh look, a surprise Route 28 traffic jam. Kidding, it's just a crash.", "Sound the alarms! A crash has been spotted on Route 28.", "You know the drill. Another crash on Route 28.", "Crashy McCrash Face just entered Route 28.", "Just when you thought your day couldn't get more exciting, Route 28 delivers another crash.", "Breaking news: The asphalt on Route 28 has once again decided to engage in an unscheduled demolition derby.", "Feeling nostalgic for the good old days? Don't worry, Route 28 just recreated a classic crash scene for you.", "My therapist told me to embrace predictability. So, naturally, I looked for a crash on Route 28.", "Yinz see that new crash on Route 28 n'at?", "New crash on Route 28 dropped!", "Route 28: Where fender-benders go to become full-time careers.", "The Route 28 crash report just hit the newsstands. Again.", "Route 28 statistics: 100% chance of existing, 90% chance of crashing.", "Warning: Route 28 may cause sudden stops, mild frustration, and existential dread.", "Route 28 just achieved its daily crash quota. Overachievers.", "Plot twist: Someone actually made it through Route 28 without crashing. Just kidding, there's been another crash.", "Route 28 crash investigators are considering opening a permanent office on-site.", "Today's Route 28 crash is brought to you by the letter 'C' and the number 'Why?'", "Route 28: Making GPS apps everywhere weep softly.", "The Route 28 crash betting pool is now accepting entries for tomorrow's incidents.", "Route 28 just achieved its personal best: three whole minutes without a crash.", "CMU Scientists baffled as Route 28 continues to attract metal objects like a magnetic disaster zone.", "Route 28 crash update: Yes, it happened. No, we're not surprised.", "Breaking: Local road continues to road badly.", "Route 28 has entered the chat. And immediately crashed.", "The Route 28 crash report is now available in audiobook format for your daily commute.", "Route 28: Now featuring premium crash experiences with extended wait times.", "Another day, another Route 28 crash. The road's consistency is truly admirable.", "Route 28 crashes have become so frequent, they're now classified as a renewable resource.", "Emergency services have installed a Route 28 crash hotline. It's just a recording that says 'We know.'", "Forget Netflix and chill, I'm just here for the live-action crash replays on Route 28.", "Route 28: Where GPS says 'In 500 feet, prepare to question all your life choices.'", "Heard a new band is forming: 'Route 28 & The Fender Benders.'"
    ]
    
    # Filter out recently used prompts
    available_prompts = [p for p in prompts if p not in recent_prompts] # New logic
    
    # If all prompts have been used recently, use all prompts
    if not available_prompts: # New logic
        available_prompts = prompts # New logic
        logging.info(f"All prompts used recently (last {len(recent_prompts)}). Using all prompts for selection.") # New logic

    intro = random.choice(available_prompts) # Modified logic
    logging.info(f"Selected prompt: '{intro}' (avoiding last {len(recent_prompts)} prompts)") # Modified log message

    lat = alert["latitude"]
    lon = alert["longitude"]
    utc_time = alert.get("publish_datetime_utc")
    if utc_time:
        try:
            # Use .%fZ for robustness with Waze timestamps
            dt = datetime.strptime(utc_time, "%Y-%m-%dT%H:%M:%S.%fZ")
            timestamp = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p on %b %d")
        except ValueError:
            timestamp = "Unknown time (parse error)"
    else:
        timestamp = "Unknown time"
    street = alert.get("street") or "an unknown street"
    city = get_city_name(lat, lon)
    # Ensure embed_url uses a valid URL format for consistency (example from plane_tracker)
    Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}" # Corrected Maps_url format
    formatted_message_text = f"🚨 {intro}\n\n📍 Location: Near {street} in {city}.\n🕒 Reported at: {timestamp}\n#Route28 #Pittsburgh #Traffic #PennDOT"
    return intro, formatted_message_text, Maps_url, f"Near {street} in {city}"

def post_to_bluesky(text, embed_url=None, embed_title=None, embed_description=None, max_retries=3):
    """
    Post to Bluesky with retry logic for temporary API errors.
    
    Args:
        text: Post content
        embed_url: Optional embed URL
        embed_title: Optional embed title
        embed_description: Optional embed description
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        bool: True if successful, False if all retries failed
    """
    for attempt in range(max_retries + 1):  # +1 because we include the initial attempt
        try:
            client = Client()
            client.login(BLSKY_HANDLE, BLSKY_APP_PASSWORD)
            embed = None
            if embed_url:
                embed = models.AppBskyEmbedExternal.Main(
                    external=models.AppBskyEmbedExternal.External(
                        uri=embed_url,
                        title=embed_title or "View on Google Maps",
                        description=embed_description or "Click to view location on Google Maps"
                    )
                )
            client.send_post(text, embed=embed)
            
            if attempt > 0:
                logging.info(f"Successfully posted to Bluesky on attempt {attempt + 1}/{max_retries + 1}.")
            else:
                logging.info("Successfully posted to Bluesky.")
            return True
            
        except Exception as e:
            if attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logging.warning(f"Bluesky post attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"All {max_retries + 1} Bluesky post attempts failed. Final error: {e}")
                return False
    
    return False  # Should never reach here, but safety fallback

def check_route_28():
    # Load initial data from disk. This is our reference for change detection.
    initial_seen_crashes_raw = load_seen_data(SEEN_FILE)
    
    # Clean initial data (e.g., filter out malformed entries before purging)
    initial_seen_crashes_clean = []
    for crash in initial_seen_crashes_raw:
        if all(k in crash for k in ['alert_id', 'publish_datetime_utc', 'lat', 'lon']):
            initial_seen_crashes_clean.append(crash)
        else:
            logging.warning(f"Malformed crash entry found in {SEEN_FILE} on load: {crash}. Skipping this entry.")

    # Purge old data. `seen_crashes_current_session` will be the active list for this run.
    seen_crashes_current_session = purge_old_crashes(initial_seen_crashes_clean)

    # --- ADD THE BOX VALIDATION CODE HERE ---
    for i, box in enumerate(ROUTE28_BOXES): # Note: using ROUTE28_BOXES here
        required_keys = ['bottom', 'top', 'left', 'right']
        if not all(key in box for key in required_keys):
            logging.critical(f"Malformed bounding box found at index {i} in ROUTE28_BOXES. Missing one or more of {required_keys}. Exiting.")
            sys.exit(1)
    # --- END OF BOX VALIDATION CODE ---

    recent_prompts = load_last_prompts(LAST_PROMPTS_FILE) # Load recent prompts list
    new_alerts_posted_this_run = False
    
    # Use a set to track alert_ids processed *within this specific run*
    current_run_processed_alert_ids = set() 

    for box in ROUTE28_BOXES:
        alerts = get_waze_alerts(box)
        logging.info(f"Total alerts received for this box: {len(alerts)}")
        for alert in alerts:
            alert_id = alert.get("alert_id")
            publish_time_utc = alert.get("publish_datetime_utc")
            
            # Skip alerts with missing critical fields
            if not alert_id or not publish_time_utc:
                logging.warning(f"Skipping alert due to missing fields: {json.dumps(alert)}")
                continue
            
            # Filter for Route 28 accidents
            if alert.get("type") == "ACCIDENT":
                street = alert.get("street") or ""
                if ("28" in street and "228" not in street) and ("SR" in street or "Route" in street or "Hwy" in street or "PA" in street):
                    
                    # Prevent processing the same alert multiple times within *this current run*
                    if alert_id in current_run_processed_alert_ids:
                        logging.info(f"Alert {alert_id} already processed in this run. Skipping.")
                        continue
                    
                    # Check against historical seen crashes (from previous runs, now in seen_crashes_current_session)
                    # Note: `seen_crashes_current_session` already contains purged valid entries.
                    if is_duplicate_incident(alert, seen_crashes_current_session):
                        logging.info(f"Alert {alert_id} skipped due to being a recent duplicate (historically seen).")
                        current_run_processed_alert_ids.add(alert_id) # Mark as processed for this run
                        continue
                    
                    # If it's a truly new, unique, and relevant crash, try to post it
                    chosen_prompt, post_text, Maps_url, embed_desc = format_alert(alert, recent_prompts) # Modified function call
                    logging.info(f"Attempting to post new alert {alert_id} to Bluesky with prompt: '{chosen_prompt}'.")
                    
                    post_successful = post_to_bluesky(post_text, embed_url=Maps_url, embed_title="View Crash Location", embed_description=embed_desc)
                    
                    if post_successful:
                        # Update recent prompts list
                        recent_prompts = add_prompt_to_history(chosen_prompt, recent_prompts) # New logic
                        save_last_prompts(recent_prompts, LAST_PROMPTS_FILE) # Save last used prompts
                        
                        # Add to the in-memory list only if successfully posted
                        seen_crashes_current_session.append({
                            "alert_id": alert_id,
                            "publish_datetime_utc": publish_time_utc,
                            "lat": alert["latitude"],
                            "lon": alert["longitude"]
                        })
                        new_alerts_posted_this_run = True
                    else:
                        logging.error(f"Bluesky post failed for alert {alert_id}. Not saving to seen_crashes to allow re-attempt later.")
                        # Do NOT add to seen_crashes_current_session if posting failed, so it can be retried in a future run.
                        # However, still add to current_run_processed_alert_ids to avoid re-attempting within THIS run.
                    
                    current_run_processed_alert_ids.add(alert_id) # Always add to this run's processed set to prevent internal duplicates


    # Final state saving logic:
    successful_posts = sum(1 for crash in seen_crashes_current_session if crash not in initial_seen_crashes_clean)
    logging.info(f"Processing summary: {len(current_run_processed_alert_ids)} alerts processed, {successful_posts} successfully posted this run")
    # Save if the in-memory list has changed due to purges OR new successful posts.
    # We compare sets of frozensets of items for robust equality check (order-agnostic).
    initial_set_of_crashes = {frozenset(d.items()) for d in initial_seen_crashes_clean}
    final_set_of_crashes = {frozenset(d.items()) for d in seen_crashes_current_session}

    if initial_set_of_crashes != final_set_of_crashes:
        save_seen_data(seen_crashes_current_session, SEEN_FILE)
        logging.info(f"Updated {SEEN_FILE} with {len(seen_crashes_current_session)} entries.")
    else:
        logging.info(f"No updates to {SEEN_FILE}.")


if __name__ == "__main__":
    logging.info(f"Script started at {datetime.now()}")
    if not all([BLSKY_HANDLE, BLSKY_APP_PASSWORD, RAPIDAPI_KEY]):
        logging.critical("Missing credentials in .env file. Exiting.")
        sys.exit(1) # Exit immediately if credentials are missing
    else:
        check_route_28()
    logging.info(f"Script finished at {datetime.now()}")
