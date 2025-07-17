import requests
import json
import os
import random
from datetime import datetime, timedelta
from atproto import Client, models  # Import models to access the embed types
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable
from geopy.distance import distance
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import time
import logging

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

# --- Configuration Constants ---
PURGE_THRESHOLD_HOURS = 24
DUPLICATE_DISTANCE_KM = 1
DUPLICATE_TIME_MINUTES = 60

# --- Bounding box for Route 28 ---
ROUTE28_BOXES = [
    {
        'bottom': 40.450, 'top': 40.700, 'left': -80.050, 'right': -79.600
    }
]

# --- Setup geocoder ---
geolocator = Nominatim(user_agent="route28-crash-watcher")

# --- Helper Functions ---
SEEN_FILE = "seen_crashes.json"
LAST_PROMPT_FILE = "last_prompt.json"

def load_last_prompt(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info(f"'{file_path}' not found or empty. Starting with no last prompt.")
        return None

def save_last_prompt(prompt_text, file_path):
    try:
        with open(file_path, 'w') as f:
            json.dump(prompt_text, f)
    except IOError as e:
        logging.error(f"Error saving last prompt to '{file_path}': {e}")

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
            crash_utc_time = datetime.strptime(crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))
            if crash_utc_time >= purge_cutoff_time:
                new_seen_crashes_list.append(crash)
        except (ValueError, KeyError):
            logging.warning(f"Malformed crash entry encountered during purge: {crash}. Keeping it for now.")
    purged_count = initial_count - len(new_seen_crashes_list)
    if purged_count > 0:
        logging.info(f"Purged {purged_count} old crash entries from {SEEN_FILE}.")
    else:
        logging.info(f"No old crash entries to purge from {SEEN_FILE}.")
    return new_seen_crashes_list

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
        logging.warning("GeocoderUnavailable error when getting city name. Returning 'unknown'.")
    except Exception as e:
        logging.error(f"Unexpected error getting city name for {lat},{lon}: {e}.")
    return "unknown"

def is_duplicate_incident(new_alert, recent_crashes):
    new_location = (new_alert['latitude'], new_alert['longitude'])
    if 'publish_datetime_utc' not in new_alert:
        logging.warning("new_alert missing 'publish_datetime_utc'. Cannot check for duplicates.")
        return False
    new_time = datetime.strptime(new_alert['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))
    for seen_crash in recent_crashes:
        if not all(k in seen_crash for k in ['lat', 'lon', 'publish_datetime_utc']):
            logging.warning(f"Malformed seen_crash entry. Skipping: {seen_crash}")
            continue
        seen_location = (seen_crash['lat'], seen_crash['lon'])
        seen_time = datetime.strptime(seen_crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=ZoneInfo("UTC"))
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
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("alerts", [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Waze data from RapidAPI: {e}")
        return []

def format_alert(alert, last_used_prompt=None):
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
        "My therapist told me to embrace predictability. So, naturally, I looked for a crash on Route 28.",
        "Yinz see that new crash on Route 28 n'at?",
        "New crash on Route 28 dropped!"
    ]
    available_prompts = [p for p in prompts if p != last_used_prompt]
    if not available_prompts:
        available_prompts = prompts
        logging.warning("All prompts used. Resetting prompt selection.")
    intro = random.choice(available_prompts)
    lat = alert["latitude"]
    lon = alert["longitude"]
    utc_time = alert.get("publish_datetime_utc")
    if utc_time:
        try:
            dt = datetime.strptime(utc_time, "%Y-%m-%dT%H:%M:%S.000Z")
            timestamp = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p on %b %d")
        except ValueError:
            timestamp = "Unknown time (parse error)"
    else:
        timestamp = "Unknown time"
    street = alert.get("street") or "an unknown street"
    city = get_city_name(lat, lon)
    Maps_url = f"https://www.google.com/maps?q={lat},{lon}"
    formatted_message_text = f"🚨 {intro}\n\n📍 Location: Near {street} in {city}.\n🕒 Reported at: {timestamp}\n#Route28 #Pittsburgh #Traffic"
    return intro, formatted_message_text, Maps_url, f"Near {street} in {city}"

def post_to_bluesky(text, embed_url=None, embed_title=None, embed_description=None):
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
        logging.info("Successfully posted to Bluesky.")
    except Exception as e:
        logging.error(f"Error posting to Bluesky: {e}")

def check_route_28():
    seen_crashes = load_seen_data(SEEN_FILE)
    last_used_prompt = load_last_prompt(LAST_PROMPT_FILE)
    seen_crashes = purge_old_crashes(seen_crashes)
    save_seen_data(seen_crashes, SEEN_FILE)
    new_alerts_posted_this_run = False
    current_run_processed_alert_ids = {crash['alert_id'] for crash in seen_crashes if 'alert_id' in crash}
    for box in ROUTE28_BOXES:
        alerts = get_waze_alerts(box)
        logging.info(f"Total alerts received for this box: {len(alerts)}")
        for alert in alerts:
            alert_id = alert.get("alert_id")
            publish_time_utc = alert.get("publish_datetime_utc")
            if not alert_id or not publish_time_utc:
                logging.warning(f"Skipping alert due to missing fields: {json.dumps(alert)}")
                continue
            if alert.get("type") == "ACCIDENT":
                street = alert.get("street") or ""
                if ("28" in street and "228" not in street) and ("SR" in street or "Route" in street or "Hwy" in street or "PA" in street):
                    if is_duplicate_incident(alert, seen_crashes):
                        logging.info(f"Alert {alert_id} skipped due to duplicate.")
                        continue
                    chosen_prompt, post_text, Maps_url, embed_desc = format_alert(alert, last_used_prompt)
                    logging.info(f"Posting new alert {alert_id} to Bluesky.")
                    post_to_bluesky(post_text, embed_url=Maps_url, embed_title="View Crash Location", embed_description=embed_desc)
                    last_used_prompt = chosen_prompt
                    save_last_prompt(last_used_prompt, LAST_PROMPT_FILE)
                    seen_crashes.append({
                        "alert_id": alert_id,
                        "publish_datetime_utc": publish_time_utc,
                        "lat": alert["latitude"],
                        "lon": alert["longitude"]
                    })
                    current_run_processed_alert_ids.add(alert_id)
                    new_alerts_posted_this_run = True
    if new_alerts_posted_this_run or len(seen_crashes) != len(load_seen_data(SEEN_FILE)):
        save_seen_data(seen_crashes, SEEN_FILE)
        logging.info(f"Updated {SEEN_FILE} with {len(seen_crashes)} entries.")
    else:
        logging.info(f"No updates to {SEEN_FILE}.")

if __name__ == "__main__":
    logging.info(f"Script started at {datetime.now()}")
    if not all([BLSKY_HANDLE, BLSKY_APP_PASSWORD, RAPIDAPI_KEY]):
        logging.critical("Missing credentials in .env file.")
    else:
        check_route_28()
    logging.info(f"Script finished at {datetime.now()}")
