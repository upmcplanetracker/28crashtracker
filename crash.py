# -*- coding: utf-8 -*-

import requests
import json
import os
import random
from datetime import datetime, timedelta
from atproto import Client, models
from geopy.geocoders import Nominatim, OpenCage
from geopy.exc import GeocoderUnavailable
from geopy.distance import distance
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import time
import logging
import sys
import re

# --- Configure Logging ---
LOG_FILE = "combined_crash_watcher.log"
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

# Bluesky Credentials for Route 28
BLSKY_HANDLE_ROUTE28 = os.getenv("BLUESKY_HANDLE_ROUTE28")
BLSKY_APP_PASSWORD_ROUTE28 = os.getenv("BLUESKY_APP_PASSWORD_ROUTE28")
MONTHLY_REPORT_GIF_PATH_ROUTE28 = os.getenv("MONTHLY_STATS_GIF_ROUTE28")

# Bluesky Credentials for Parkway East
BLSKY_HANDLE_PARKWAYEAST = os.getenv("BLUESKY_HANDLE_PARKWAYEAST")
BLSKY_APP_PASSWORD_PARKWAYEAST = os.getenv("BLUESKY_APP_PASSWORD_PARKWAYEAST")
MONTHLY_REPORT_GIF_PATH_PARKWAYEAST = os.getenv("MONTHLY_STATS_GIF_PARKWAYEAST")

# General API Keys
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY")

# --- Configuration Constants ---
PURGE_THRESHOLD_HOURS = 24
DUPLICATE_DISTANCE_KM = 1
DUPLICATE_TIME_MINUTES = 45
MAX_WAZE_API_RETRIES = 4
MAX_RECENT_PROMPTS = 12

# --- Combined Bounding Box for Pittsburgh Area (adjust as needed) ---
# This box should encompass both Route 28 and Parkway East areas
# Route 28: bottom: 40.450, top: 40.700, left: -80.050, right: -79.600
# Parkway East: bottom: 40.404, top: 40.587, left: -80.25, right: -79.747
# A larger box covering both:
COMBINED_BOUNDING_BOX = {
    'bottom': 40.400, 'top': 40.750, 'left': -80.300, 'right': -79.550
}

# --- Setup geocoder ---
# Using a generic user agent for the combined script
geolocator = Nominatim(user_agent="pittsburgh-crash-watcher")
opencage_geolocator = None
if OPENCAGE_API_KEY:
    opencage_geolocator = OpenCage(api_key=OPENCAGE_API_KEY, user_agent="pittsburgh-crash-watcher-opencage")
else:
    logging.warning("OPENCAGE_API_KEY not found in .env. OpenCage geocoding failover will not be available.")

# --- File Paths for each road system ---
FILE_PATHS = {
    "ROUTE28": {
        "SEEN_FILE": "seen_crashes_route28.json",
        "LAST_PROMPTS_FILE": "last_prompts_route28.json",
        "MONTHLY_CRASH_FILE": "monthly_crash_data_route28.json",
        "BLUESKY_HANDLE": BLSKY_HANDLE_ROUTE28,
        "BLUESKY_APP_PASSWORD": BLSKY_APP_PASSWORD_ROUTE28,
        "MONTHLY_REPORT_GIF_PATH": MONTHLY_REPORT_GIF_PATH_ROUTE28,
        "PROMPTS": [
            "Guess what? Another crash on Route 28!", "Reset the 'Days Since Last Crash on Route 28' counter to zero.", "Route 28 is at it again. A crash has been reported.", "If you had 'Crash on Route 28' on your bingo card, congratulations.", "Oh look, a surprise Route 28 traffic jam. Kidding, it's just a crash.", "Sound the alarms! A crash has been spotted on Route 28.", "You know the drill. Another crash on Route 28.", "Crashy McCrash Face just entered Route 28.", "Just when you thought your day couldn't get more exciting, Route 28 delivers another crash.", "Breaking news: The asphalt on Route 28 has once again decided to engage in an unscheduled demolition derby.", "Feeling nostalgic for the good old days? Don't worry, Route 28 just recreated a classic crash scene for you.", "My therapist told me to embrace predictability. So, naturally, I looked for a crash on Route 28.", "Yinz see that new crash on Route 28 n'at?", "New crash on Route 28 dropped!", "Route 28: Where fender-benders go to become full-time careers.", "The Route 28 crash report just hit the newsstands. Again.", "Route 28 statistics: 100% chance of existing, 90% chance of crashing.", "Warning: Route 28 may cause sudden stops, mild frustration, and existential dread.", "Route 28 just achieved its daily crash quota. Overachievers.", "Plot twist: Someone actually made it through Route 28 without crashing. Just kidding, there's been another crash.", "Route 28 crash investigators are considering opening a permanent office on-site.", "Today's Route 28 crash is brought to you by the letter 'C' and the number 'Why?'", "Route 28: Making GPS apps everywhere weep softly.", "The Route 28 crash betting pool is now accepting entries for tomorrow's incidents.", "Route 28 just achieved its personal best: three whole minutes without a crash.", "CMU Scientists baffled as Route 28 continues to attract metal objects like a magnetic disaster zone.", "Route 28 crash update: Yes, it happened. No, we're not surprised.", "Breaking: Local road continues to road badly.", "Route 28 has entered the chat. And immediately crashed.", "The Route 28 crash report is now available in audiobook format for your daily commute.", "Route 28: Now featuring premium crash experiences with extended wait times.", "Another day, another Route 28 crash. The road's consistency is truly admirable.", "Route 28 crashes have become so frequent, they're now classified as a renewable resource.", "Emergency services have installed a Route 28 crash hotline. It's just a recording that says 'We know.'", "Forget Netflix and chill, I'm just here for the live-action crash replays on Route 28.", "Route 28: Where GPS says 'In 500 feet, prepare to question all your life choices.'", "Heard a new band is forming: 'Route 28 & The Fender Benders.'"
        ],
        "REPORT_MESSAGE_TEMPLATE": (
            "🚨 Monthly Crash Report for {reported_month_name} {reported_year}:\n"
            "There were {total_crashes_last_month} car crashes detected on or near Route 28 in {reported_month_name}.\n"
            "#Pittsburgh #Traffic #Route28 #PennDOT #MonthlyReport"
        ),
        "EMOJIS": {"intro": "🚨", "location": "📍", "reported_at": "⌚"}
    },
    "PARKWAYEAST": {
        "SEEN_FILE": "seen_crashes_parkwayeast.json",
        "LAST_PROMPTS_FILE": "last_prompts_parkwayeast.json",
        "MONTHLY_CRASH_FILE": "monthly_crash_data_parkwayeast.json",
        "BLUESKY_HANDLE": BLSKY_HANDLE_PARKWAYEAST,
        "BLUESKY_APP_PASSWORD": BLSKY_APP_PASSWORD_PARKWAYEAST,
        "MONTHLY_REPORT_GIF_PATH": MONTHLY_REPORT_GIF_PATH_PARKWAYEAST,
        "PROMPTS": [
            "Guess what? Another crash on the Parkway!", "Reset the 'Days Since Last Crash on the Parkway' counter to zero.", "The Parkway is at it again. A crash has been reported.", "If you had 'Crash on the Parkway' on your bingo card, congratulations.", "Oh look, a surprise Parkway traffic jam. Kidding, it's just a crash.", "Sound the alarms! A crash has been spotted on the Parkway.", "You know the drill. Another crash on the Parkway.", "Crashy McCrash Face just entered the Parkway.", "Just when you thought your day couldn't get more exciting, the Parkway delivers another crash.", "Breaking news: The asphalt on the Parkway has once again decided to engage in an unscheduled demolition derby.", "Feeling nostalgic for the good old days? Don't worry, the Parkway just recreated a classic crash scene for you.", "My therapist told me to embrace predictability. So, naturally, I looked for a crash on the Parkway.", "Yinz see that new crash on the Parkway n'at?", "New crash on the Parkway dropped!", "The Parkway just announced its latest limited-time offer: a complimentary traffic jam with every crash.", "Rumor has it, the Parkway is auditioning for the next 'Fast & Furious' movie. Lots of crashes, little progress.", "If life gives you lemons, you're probably stuck on the Parkway behind a crash.", "My doctor prescribed less stress, then I drove on the Parkway. It's a work in progress.", "Just spotted a rare phenomenon on the Parkway: a car *not* involved in a crash. Send pics!", "The Parkway's motto: 'We may not get you there fast, but we'll certainly make it memorable.'", "Is it just me, or does the Parkway have a personal vendetta against my commute time?"
        ],
        "REPORT_MESSAGE_TEMPLATE": (
            "🚗 Monthly Crash Report for {reported_month_name} {reported_year}:\n"
            "There were {total_crashes_last_month} car crashes detected on or near the Parkways in {reported_month_name}.\n"
            "#Pittsburgh #Traffic #Parkway #PennDOT #MonthlyReport"
        ),
        "EMOJIS": {"intro": "🚨", "location": "📍", "reported_at": "⌚"}
    }
}


# --- Helper Functions ---

def load_json_data(file_path, default_value=None):
    """Load JSON data from a file."""
    if default_value is None:
        default_value = []
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.info(f"'{file_path}' not found. Starting with default data.")
        return default_value
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from '{file_path}'. Starting with default data.")
        return default_value
    except IOError as e:
        logging.critical(f"Permission error or other I/O error reading '{file_path}': {e}. Cannot load data.")
        return default_value

def save_json_data(data, file_path):
    """Save JSON data to a file."""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logging.error(f"Error saving data to '{file_path}': {e}")

def load_last_prompts(file_path):
    """Load the list of recently used prompts"""
    data = load_json_data(file_path, default_value=[])
    if isinstance(data, str): # Handle case where it might be a single string
        return [data]
    elif isinstance(data, list):
        return data
    else:
        logging.warning(f"Unexpected data format in '{file_path}'. Starting with empty list.")
        return []

def save_last_prompts(prompts_list, file_path):
    """Save the list of recently used prompts"""
    save_json_data(prompts_list, file_path)

def add_prompt_to_history(new_prompt, prompts_list, max_prompts=MAX_RECENT_PROMPTS):
    """Add a new prompt to the history and maintain the maximum count"""
    if new_prompt in prompts_list:
        prompts_list.remove(new_prompt)
    
    prompts_list.insert(0, new_prompt)
    
    return prompts_list[:max_prompts]

def purge_old_crashes(seen_data_list):
    current_time = datetime.now(ZoneInfo("UTC"))
    purge_cutoff_time = current_time - timedelta(hours=PURGE_THRESHOLD_HOURS)
    initial_count = len(seen_data_list)
    new_seen_crashes_list = []
    for crash in seen_data_list:
        try:
            # Ensure the timestamp is correctly parsed with .%fZ for robustness with Waze timestamps
            crash_utc_time = datetime.strptime(crash['publish_datetime_utc'], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=ZoneInfo("UTC"))
            if crash_utc_time >= purge_cutoff_time:
                new_seen_crashes_list.append(crash)
        except (ValueError, KeyError) as e:
            logging.warning(f"Malformed crash entry encountered during purge: {crash}. Error: {e}. Skipping this entry.")
            continue
    purged_count = initial_count - len(new_seen_crashes_list)
    if purged_count > 0:
        logging.info(f"Purged {purged_count} old crash entries.")
    else:
        logging.info(f"No old crash entries to purge.")
    return new_seen_crashes_list

def get_city_name(lat, lon):
    city = "unknown"

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
            if city:
                return city
    except GeocoderUnavailable:
        logging.warning("Nominatim GeocoderUnavailable. Falling back to OpenCage.")
    except Exception as e:
        logging.warning(f"Nominatim lookup failed unexpectedly for {lat},{lon}: {e}. Falling back to OpenCage.")

    if opencage_geolocator:
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
                if city:
                    logging.info(f"Successfully retrieved city from OpenCage for {lat},{lon}.")
                    return city
        except Exception as e:
            logging.error(f"OpenCage geocoding failed for {lat},{lon}: {e}.")
    else:
        logging.debug("OpenCage geolocator not initialized (API key missing or failed init).")

    logging.warning(f"Could not determine city name for {lat},{lon} using any geocoder.")
    return "unknown"

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

    for attempt in range(MAX_WAZE_API_RETRIES + 1):
        logging.debug(f"Attempt {attempt + 1}/{MAX_WAZE_API_RETRIES + 1} to query Waze with box: {querystring}")
        try:
            resp = requests.get(url, headers=headers, params=querystring, timeout=30)
            resp.raise_for_status()
            logging.info(f"Accessed Waze successfully on try #{attempt + 1}.")
            data = resp.json()
            return data.get("data", {}).get("alerts", [])
        except requests.exceptions.RequestException as e:
            if attempt < MAX_WAZE_API_RETRIES:
                wait_time = 2 ** attempt
                logging.warning(f"Error fetching Waze data from RapidAPI (attempt {attempt + 1}/{MAX_WAZE_API_RETRIES + 1}): {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"Failed to fetch Waze data after {MAX_WAZE_API_RETRIES + 1} attempts. Final error: {e}")
                return []

def format_alert(alert, recent_prompts, road_type_config):
    """Format alert with prompt selection that avoids recently used prompts"""
    
    prompts = road_type_config["PROMPTS"]
    emojis = road_type_config["EMOJIS"]

    # Filter out recently used prompts
    available_prompts = [p for p in prompts if p not in recent_prompts]
    
    # If all prompts have been used recently, use all prompts
    if not available_prompts:
        available_prompts = prompts
        logging.info(f"All prompts used recently (last {len(recent_prompts)}). Using all prompts for selection.")

    intro = random.choice(available_prompts)
    logging.info(f"Selected prompt: '{intro}' (avoiding last {len(recent_prompts)} prompts)")

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
    Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    
    formatted_message_text = (
        f"{emojis['intro']} {intro}\n\n"
        f"{emojis['location']} Location: Near {street} in {city}.\n"
        f"{emojis['reported_at']} Reported at: {timestamp}\n"
        f"#Pittsburgh #Traffic #PennDOT"
    )
    return intro, formatted_message_text, Maps_url, f"Near {street} in {city}"

def post_to_bluesky(text, bluesky_handle, bluesky_password, embed_url=None, embed_title=None, embed_description=None, local_image_path=None, max_retries=3):
    """
    Post to Bluesky with retry logic, supporting external link embeds OR a single local image/GIF embed.
    
    Args:
        text: Post content
        bluesky_handle: The Bluesky handle to post from.
        bluesky_password: The Bluesky app password for the handle.
        embed_url: Optional URL for an external link embed.
        embed_title: Optional title for the external link embed.
        embed_description: Optional description for the external link embed.
        local_image_path: Optional path to a local image/GIF file to embed.
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        bool: True if successful, False if all retries failed
    """
    if not bluesky_handle or not bluesky_password:
        logging.error("Bluesky handle or password not provided. Cannot post.")
        return False

    for attempt in range(max_retries + 1):
        try:
            client = Client()
            client.login(bluesky_handle, bluesky_password)
            
            main_embed = None

            if local_image_path:
                try:
                    with open(local_image_path, 'rb') as f:
                        img_bytes = f.read()
                    
                    if local_image_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                        mime_type = "image/jpeg"
                        if local_image_path.lower().endswith('.png'):
                            mime_type = "image/png"
                    elif local_image_path.lower().endswith('.gif'):
                        mime_type = "image/gif"
                    else:
                        logging.warning(f"Could not determine MIME type for {local_image_path}. Defaulting to image/jpeg.")
                        mime_type = "image/jpeg"

                    logging.info(f"Uploading local image/GIF from {local_image_path} to Bluesky for {bluesky_handle}...")
                    upload_response = client.upload_blob(img_bytes, content_type=mime_type)
                    
                    main_embed = models.AppBskyEmbedImages.Main(
                        images=[
                            models.AppBskyEmbedImages.Image(
                                image=upload_response,
                                alt="The Count from Sesame Street counting crashes" # Mandatory alt text
                            )
                        ]
                    )
                    logging.info(f"Local image/GIF blob uploaded successfully for {local_image_path}.")

                except FileNotFoundError:
                    logging.error(f"Local image file not found: {local_image_path}. Skipping image embed.")
                except Exception as e:
                    logging.error(f"Error during local image/GIF upload for {local_image_path}: {e}. Skipping image embed.")
            
            if not main_embed and embed_url:
                main_embed = models.AppBskyEmbedExternal.Main(
                    external=models.AppBskyEmbedExternal.External(
                        uri=embed_url,
                        title=embed_title or "View on Google Maps",
                        description=embed_description or "Click to view location on Google Maps"
                    )
                )

            client.send_post(text, embed=main_embed)
            
            if attempt > 0:
                logging.info(f"Successfully posted to Bluesky ({bluesky_handle}) on attempt {attempt + 1}/{max_retries + 1}.")
            else:
                logging.info(f"Successfully posted to Bluesky ({bluesky_handle}).")
            return True
            
        except Exception as e:
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logging.warning(f"Bluesky post attempt {attempt + 1}/{max_retries + 1} for {bluesky_handle} failed: {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"All {max_retries + 1} Bluesky post attempts for {bluesky_handle} failed. Final error: {e}")
                return False
    
    return False

def load_monthly_crash_data(file_path):
    """Loads the monthly crash data from a JSON file.
       If the file is not found, it initializes and SAVES default data.
    """
    try:
        data = load_json_data(file_path)
        # Ensure it's a dict and has expected keys, otherwise re-initialize
        if not isinstance(data, dict) or "current_month_crashes" not in data or "last_reset_date" not in data:
            logging.warning(f"Malformed monthly crash data in '{file_path}'. Re-initializing.")
            raise json.JSONDecodeError("Malformed data", doc="", pos=0) # Trigger re-initialization
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info(f"'{file_path}' not found or empty/corrupted. Initializing and creating with default data.")
        default_data = {"current_month_crashes": 0, "last_reset_date": datetime.now().strftime("%Y-%m-%d")}
        save_json_data(default_data, file_path) # Save it immediately
        logging.info(f"'{file_path}' successfully created with initial data.")
        return default_data
    except IOError as e:
        logging.critical(f"Permission error or other I/O error reading '{file_path}': {e}. Cannot load monthly crash data. Proceeding with in-memory default data.")
        return {"current_month_crashes": 0, "last_reset_date": datetime.now().strftime("%Y-%m-%d")}

def save_monthly_crash_data(data, file_path):
    """Saves the monthly crash data to a JSON file."""
    save_json_data(data, file_path)

def increment_monthly_counter(file_path):
    """Increments the monthly crash counter."""
    data = load_monthly_crash_data(file_path)
    data["current_month_crashes"] += 1
    save_monthly_crash_data(data, file_path)
    logging.info(f"Monthly crash counter for {file_path} incremented. Current count: {data['current_month_crashes']}")

def handle_monthly_reset_and_report(road_type_key):
    """
    Checks if it's the end of the month and handles reporting and resetting for a specific road type.
    """
    config = FILE_PATHS[road_type_key]
    data = load_monthly_crash_data(config["MONTHLY_CRASH_FILE"])

    current_date = datetime.now()
    last_reset_dt = datetime.strptime(data["last_reset_date"], "%Y-%m-%d") 

    next_month = current_date.replace(day=28) + timedelta(days=4)
    last_day_of_current_month = next_month - timedelta(days=next_month.day)

    target_time_check = current_date.replace(hour=12, minute=59, second=0, microsecond=0)
    
    is_end_of_month_and_time = (
        current_date.day == last_day_of_current_month.day and
        current_date >= target_time_check and
        current_date.month != last_reset_dt.month
    )
    
    is_start_of_new_month = (
        current_date.day == 1 and
        current_date.month != last_reset_dt.month
    )

    if is_end_of_month_and_time or is_start_of_new_month:
        reported_month_dt = current_date - timedelta(days=1) if is_start_of_new_month else current_date
        reported_month_name = reported_month_dt.strftime("%B")
        reported_year = reported_month_dt.year

        total_crashes_last_month = data["current_month_crashes"]
        
        report_message = config["REPORT_MESSAGE_TEMPLATE"].format(
            reported_month_name=reported_month_name,
            reported_year=reported_year,
            total_crashes_last_month=total_crashes_last_month
        )
        logging.info(f"Attempting to post monthly report for {road_type_key}: {report_message}")
        
        post_successful = post_to_bluesky(
            report_message,
            bluesky_handle=config["BLUESKY_HANDLE"],
            bluesky_password=config["BLUESKY_APP_PASSWORD"],
            embed_title=f"Monthly {road_type_key.replace('ROUTE', 'Route ').replace('PARKWAYEAST', 'Parkway East')} Crash Report",
            local_image_path=config["MONTHLY_REPORT_GIF_PATH"]
        )

        if post_successful:
            logging.info(f"Monthly crash report for {road_type_key} posted successfully.")
            data["current_month_crashes"] = 0
            data["last_reset_date"] = current_date.strftime("%Y-%m-%d")
            save_monthly_crash_data(data, config["MONTHLY_CRASH_FILE"])
            logging.info(f"Monthly crash counter for {road_type_key} reset to 0.")
        else:
            logging.error(f"Failed to post monthly crash report for {road_type_key} to Bluesky.")
    else:
        logging.info(f"Not the end of the month for {road_type_key} reporting/resetting or already processed for this month.")

def classify_alert_by_road(alert):
    """
    Classifies a Waze alert based on its street name to determine if it's Route 28 or Parkway East.
    Returns "ROUTE28", "PARKWAYEAST", or "UNKNOWN".
    """
    street = alert.get("street") or ""
    street_upper = street.upper()

    # Check for Route 28
    if (re.search(r'\b(ROUTE|RT|US|STATE ROUTE|PA)[ -]?28\b', street, re.IGNORECASE) or \
       ("28" in street and "228" not in street and "128" not in street and "286" not in street and "328" not in street and "428" not in street and "528" not in street)) and \
       ("BUS" not in street_upper):
        return "ROUTE28"
    
    # Check for Parkway East (I-376)
    if (("FT PITT TUNNEL" in street_upper or "FORT PITT TUNNEL" in street_upper or "FT PITT TUN" in street_upper or "279" in street_upper or "I-279" in street_upper or "376" in street_upper or "I-376" in street_upper or "PARKWAY" in street_upper or "PARKWAY EAST" in street_upper or "PARKWAY NORTH" in street_upper or "PARKWAY WEST" in street_upper or "579" in street_upper or "I-579" in street_upper or "PARKWAY W" in street_upper or "PARKWAY N" in street_upper or "PARKWAY E" in street_upper or re.search(r"VET(\w*) BRIDGE", street_upper) or "LIBERTY BRIDGE" in street_upper or "LIBERTY BR" in street_upper) and "BUS" not in street_upper):
        return "PARKWAYEAST"
    
    return "UNKNOWN"

def process_crashes():
    """
    Fetches Waze alerts for the combined bounding box, classifies them,
    and posts to the appropriate Bluesky account while updating counters.
    """
    # Initialize seen crashes and recent prompts for both road types
    seen_crashes = {
        "ROUTE28": purge_old_crashes(load_json_data(FILE_PATHS["ROUTE28"]["SEEN_FILE"], default_value=[])),
        "PARKWAYEAST": purge_old_crashes(load_json_data(FILE_PATHS["PARKWAYEAST"]["SEEN_FILE"], default_value=[]))
    }
    recent_prompts = {
        "ROUTE28": load_last_prompts(FILE_PATHS["ROUTE28"]["LAST_PROMPTS_FILE"]),
        "PARKWAYEAST": load_last_prompts(FILE_PATHS["PARKWAYEAST"]["LAST_PROMPTS_FILE"])
    }

    initial_seen_crashes_route28 = {frozenset(d.items()) for d in seen_crashes["ROUTE28"]}
    initial_seen_crashes_parkwayeast = {frozenset(d.items()) for d in seen_crashes["PARKWAYEAST"]}

    new_alerts_posted_this_run = {
        "ROUTE28": False,
        "PARKWAYEAST": False
    }
    
    current_run_processed_alert_ids = set() # To prevent processing the same alert multiple times in one run

    logging.info(f"Fetching Waze alerts for combined bounding box: {COMBINED_BOUNDING_BOX}")
    alerts = get_waze_alerts(COMBINED_BOUNDING_BOX)
    logging.info(f"Total alerts received for combined box: {len(alerts)}")

    for alert in alerts:
        alert_id = alert.get("alert_id")
        publish_time_utc = alert.get("publish_datetime_utc")
        
        if not alert_id or not publish_time_utc:
            logging.warning(f"Skipping alert due to missing fields: {json.dumps(alert)}")
            continue
        
        if alert.get("type") == "ACCIDENT":
            # Check if this alert has already been processed in this run
            if alert_id in current_run_processed_alert_ids:
                logging.info(f"Alert {alert_id} already processed in this run. Skipping.")
                continue

            road_type = classify_alert_by_road(alert)
            
            if road_type in FILE_PATHS: # Check if it's a recognized road type
                config = FILE_PATHS[road_type]
                
                if is_duplicate_incident(alert, seen_crashes[road_type]):
                    logging.info(f"Alert {alert_id} for {road_type} skipped due to being a recent duplicate (historically seen).")
                    current_run_processed_alert_ids.add(alert_id)
                    continue
                
                chosen_prompt, post_text, Maps_url, embed_desc = format_alert(alert, recent_prompts[road_type], config)
                logging.info(f"Attempting to post new alert {alert_id} for {road_type} to Bluesky with prompt: '{chosen_prompt}'.")
                
                post_successful = post_to_bluesky(
                    post_text, 
                    bluesky_handle=config["BLUESKY_HANDLE"], 
                    bluesky_password=config["BLUESKY_APP_PASSWORD"],
                    embed_url=Maps_url, 
                    embed_title="View Crash Location", 
                    embed_description=embed_desc
                )
                
                if post_successful:
                    increment_monthly_counter(config["MONTHLY_CRASH_FILE"])

                    recent_prompts[road_type] = add_prompt_to_history(chosen_prompt, recent_prompts[road_type])
                    save_last_prompts(recent_prompts[road_type], config["LAST_PROMPTS_FILE"])
                    
                    seen_crashes[road_type].append({
                        "alert_id": alert_id,
                        "publish_datetime_utc": publish_time_utc,
                        "lat": alert["latitude"],
                        "lon": alert["longitude"]
                    })
                    new_alerts_posted_this_run[road_type] = True
                else:
                    logging.error(f"Bluesky post failed for alert {alert_id} for {road_type}. Not saving to seen_crashes to allow re-attempt later.")
                
                current_run_processed_alert_ids.add(alert_id)
            else:
                logging.info(f"Alert {alert_id} at {alert.get('street')} does not match any configured road type. Skipping.")

    # Save updated seen_crashes and recent_prompts for each road type
    for road_type_key, config in FILE_PATHS.items():
        final_set_of_crashes = {frozenset(d.items()) for d in seen_crashes[road_type_key]}
        
        # Compare with initial state to decide if saving is needed
        if road_type_key == "ROUTE28":
            initial_set = initial_seen_crashes_route28
        elif road_type_key == "PARKWAYEAST":
            initial_set = initial_seen_crashes_parkwayeast
        
        if initial_set != final_set_of_crashes:
            save_json_data(seen_crashes[road_type_key], config["SEEN_FILE"])
            logging.info(f"Updated {config['SEEN_FILE']} with {len(seen_crashes[road_type_key])} entries.")
        else:
            logging.info(f"No updates to {config['SEEN_FILE']}.")

        save_last_prompts(recent_prompts[road_type_key], config["LAST_PROMPTS_FILE"])


if __name__ == "__main__":
    logging.info(f"Script started at {datetime.now()}")
    
    # Check for general RapidAPI key and OpenCage key
    if not RAPIDAPI_KEY:
        logging.critical("Missing RAPIDAPI_KEY in .env file. Exiting.")
        sys.exit(1)
    
    # Check for Bluesky credentials for each road type
    missing_bluesky_creds = []
    if not BLSKY_HANDLE_ROUTE28 or not BLSKY_APP_PASSWORD_ROUTE28:
        missing_bluesky_creds.append("Route 28 Bluesky credentials")
    if not BLSKY_HANDLE_PARKWAYEAST or not BLSKY_APP_PASSWORD_PARKWAYEAST:
        missing_bluesky_creds.append("Parkway East Bluesky credentials")

    if missing_bluesky_creds:
        logging.critical(f"Missing credentials in .env file: {', '.join(missing_bluesky_creds)}. Exiting.")
        sys.exit(1)

    # Handle monthly reports for each road type
    for road_type_key in FILE_PATHS.keys():
        handle_monthly_reset_and_report(road_type_key)
        
    # Process new crashes
    process_crashes()
    
    logging.info(f"Script finished at {datetime.now()}")
