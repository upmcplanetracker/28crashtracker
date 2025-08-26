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
import re  # Added this import if not already present, necessary for the re.search in check_route_28

# Try to import tweepy for X.com API support
try:
    import tweepy

    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False
    logging.warning(
        "tweepy not available. X.com posting will not work. Install with: pip install tweepy"
    )

# --- Configure Logging ---
LOG_FILE = "route28_watcher.log"
FILE_LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=FILE_LOG_LEVEL,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

# --- Load credentials from .env file ---
load_dotenv()
BLSKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLSKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY")
MONTHLY_REPORT_GIF_PATH = os.getenv("MONTHLY_STATS_GIF")

# X.com API credentials
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

# Platform selection - set to 'bluesky' or 'x' in .env file
POSTING_PLATFORM = os.getenv("POSTING_PLATFORM", "bluesky").lower()

# --- Configuration Constants ---
PURGE_THRESHOLD_HOURS = 24
DUPLICATE_DISTANCE_KM = 1
DUPLICATE_TIME_MINUTES = 45
MAX_WAZE_API_RETRIES = 4
MAX_RECENT_PROMPTS = 12

# --- Bounding box for Route 28 ---
ROUTE28_BOXES = [{"bottom": 40.450, "top": 40.700, "left": -80.050, "right": -79.600}]

# --- Setup geocoder ---
geolocator = Nominatim(user_agent="route28-crash-watcher")
opencage_geolocator = None
if OPENCAGE_API_KEY:
    opencage_geolocator = OpenCage(
        api_key=OPENCAGE_API_KEY, user_agent="route28-crash-watcher-opencage"
    )
else:
    logging.warning(
        "OPENCAGE_API_KEY not found in .env. OpenCage geocoding failover will not be available."
    )

# --- Helper Functions ---
SEEN_FILE = "seen_crashes.json"
LAST_PROMPTS_FILE = "last_prompts_route28.json"
MONTHLY_CRASH_FILE = "monthly_crash_data_route28.json"


def load_last_prompts(file_path):
    """Load the list of recently used prompts"""
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            if isinstance(data, str):
                return [data]
            elif isinstance(data, list):
                return data
            else:
                logging.warning(
                    f"Unexpected data format in '{file_path}'. Starting with empty list."
                )
                return []
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info(
            f"'{file_path}' not found or empty. Starting with no recent prompts."
        )
        return []
    except IOError as e:
        logging.critical(
            f"Permission error or other I/O error reading '{file_path}': {e}. Cannot load recent prompts."
        )
        return []


def save_last_prompts(prompts_list, file_path):
    """Save the list of recently used prompts"""
    try:
        with open(file_path, "w") as f:
            json.dump(prompts_list, f, indent=2)
    except IOError as e:
        logging.error(f"Error saving recent prompts to '{file_path}': {e}")


def add_prompt_to_history(new_prompt, prompts_list, max_prompts=MAX_RECENT_PROMPTS):
    """Add a new prompt to the history and maintain the maximum count"""
    if new_prompt in prompts_list:
        prompts_list.remove(new_prompt)

    prompts_list.insert(0, new_prompt)

    return prompts_list[:max_prompts]


def load_seen_data(file_path):
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.info(f"'{file_path}' not found. Starting with empty data.")
        return []
    except json.JSONDecodeError:
        logging.error(
            f"Error decoding JSON from '{file_path}'. Starting with empty data."
        )
        return []
    except IOError as e:
        logging.critical(
            f"Permission error or other I/O error reading '{file_path}': {e}. Cannot load seen data."
        )
        return []


def save_seen_data(data, file_path):
    try:
        with open(file_path, "w") as f:
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
            crash_utc_time = datetime.strptime(
                crash["publish_datetime_utc"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=ZoneInfo("UTC"))
            if crash_utc_time >= purge_cutoff_time:
                new_seen_crashes_list.append(crash)
        except (ValueError, KeyError) as e:
            logging.warning(
                f"Malformed crash entry encountered during purge: {crash}. Error: {e}. Skipping this entry."
            )
            continue
    purged_count = initial_count - len(new_seen_crashes_list)
    if purged_count > 0:
        logging.info(f"Purged {purged_count} old crash entries from {SEEN_FILE}.")
    else:
        logging.info(f"No old crash entries to purge from {SEEN_FILE}.")
    return new_seen_crashes_list


def get_city_name(lat, lon):
    city = "unknown"

    try:
        logging.debug(f"Attempting Nominatim for {lat},{lon}")
        location = geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
        if location and "address" in location.raw:
            address = location.raw["address"]
            city = (
                address.get("municipality")
                or address.get("city")
                or address.get("town")
                or address.get("village")
            )
            if city:
                return city
    except GeocoderUnavailable:
        logging.warning("Nominatim GeocoderUnavailable. Falling back to OpenCage.")
    except Exception as e:
        logging.warning(
            f"Nominatim lookup failed unexpectedly for {lat},{lon}: {e}. Falling back to OpenCage."
        )

    if opencage_geolocator:
        try:
            logging.debug(f"Attempting OpenCage for {lat},{lon}")
            location_opencage = opencage_geolocator.reverse(
                (lat, lon), exactly_one=True, timeout=10
            )
            if location_opencage and "address" in location_opencage.raw:
                address_opencage = location_opencage.raw["address"]
                city = (
                    address_opencage.get("municipality")
                    or address_opencage.get("city")
                    or address_opencage.get("town")
                    or address_opencage.get("village")
                )
                if city:
                    logging.info(
                        f"Successfully retrieved city from OpenCage for {lat},{lon}."
                    )
                    return city
        except Exception as e:
            logging.error(f"OpenCage geocoding failed for {lat},{lon}: {e}.")
    else:
        logging.debug(
            "OpenCage geolocator not initialized (API key missing or failed init)."
        )

    logging.warning(
        f"Could not determine city name for {lat},{lon} using any geocoder."
    )
    return "unknown"


def is_duplicate_incident(new_alert, recent_crashes):
    new_location = (new_alert["latitude"], new_alert["longitude"])
    if "publish_datetime_utc" not in new_alert:
        logging.warning(
            "new_alert missing 'publish_datetime_utc'. Cannot check for duplicates."
        )
        return False
    # Use .%fZ for robustness with Waze timestamps
    new_time = datetime.strptime(
        new_alert["publish_datetime_utc"], "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=ZoneInfo("UTC"))

    for seen_crash in recent_crashes:
        if not all(k in seen_crash for k in ["lat", "lon", "publish_datetime_utc"]):
            logging.warning(f"Malformed seen_crash entry. Skipping: {seen_crash}")
            continue
        seen_location = (seen_crash["lat"], seen_crash["lon"])
        # Use .%fZ for robustness with Waze timestamps
        seen_time = datetime.strptime(
            seen_crash["publish_datetime_utc"], "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=ZoneInfo("UTC"))
        time_difference = abs((new_time - seen_time).total_seconds()) / 60
        if time_difference <= DUPLICATE_TIME_MINUTES:
            try:
                if distance(new_location, seen_location).km < DUPLICATE_DISTANCE_KM:
                    logging.info(
                        f"Duplicate found: Near {seen_location} reported at {seen_time.astimezone(ZoneInfo('America/New_York')).strftime('%-I:%M %p')} (diff: {time_difference:.1f} min)"
                    )
                    return True
            except ValueError as e:
                logging.error(
                    f"Error calculating distance: {e}. Locations: {new_location}, {seen_location}"
                )
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
        "alert_types": "ACCIDENT",
    }
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "waze.p.rapidapi.com"}

    for attempt in range(MAX_WAZE_API_RETRIES + 1):
        logging.debug(
            f"Attempt {attempt + 1}/{MAX_WAZE_API_RETRIES + 1} to query Waze with box: {querystring}"
        )
        try:
            resp = requests.get(url, headers=headers, params=querystring, timeout=30)
            resp.raise_for_status()
            logging.info(f"Accessed Waze successfully on try #{attempt + 1}.")
            data = resp.json()
            return data.get("data", {}).get("alerts", [])
        except requests.exceptions.RequestException as e:
            if attempt < MAX_WAZE_API_RETRIES:
                wait_time = 2**attempt
                logging.warning(
                    f"Error fetching Waze data from RapidAPI (attempt {attempt + 1}/{MAX_WAZE_API_RETRIES + 1}): {e}. Retrying in {wait_time} seconds..."
                )
                time.sleep(wait_time)
            else:
                logging.error(
                    f"Failed to fetch Waze data after {MAX_API_RETRIES + 1} attempts. Final error: {e}"
                )
                return []


def format_alert(alert, recent_prompts=None):
    """Format alert with prompt selection that avoids recently used prompts"""
    if recent_prompts is None:
        recent_prompts = []

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
        "New crash on Route 28 dropped!",
        "Route 28: Where fender-benders go to become full-time careers.",
        "The Route 28 crash report just hit the newsstands. Again.",
        "Route 28 statistics: 100% chance of existing, 90% chance of crashing.",
        "Warning: Route 28 may cause sudden stops, mild frustration, and existential dread.",
        "Route 28 just achieved its daily crash quota. Overachievers.",
        "Plot twist: Someone actually made it through Route 28 without crashing. Just kidding, there's been another crash.",
        "Route 28 crash investigators are considering opening a permanent office on-site.",
        "Today's Route 28 crash is brought to you by the letter 'C' and the number 'Why?'",
        "Route 28: Making GPS apps everywhere weep softly.",
        "The Route 28 crash betting pool is now accepting entries for tomorrow's incidents.",
        "Route 28 just achieved its personal best: three whole minutes without a crash.",
        "CMU Scientists baffled as Route 28 continues to attract metal objects like a magnetic disaster zone.",
        "Route 28 crash update: Yes, it happened. No, we're not surprised.",
        "Breaking: Local road continues to road badly.",
        "Route 28 has entered the chat. And immediately crashed.",
        "The Route 28 crash report is now available in audiobook format for your daily commute.",
        "Route 28: Now featuring premium crash experiences with extended wait times.",
        "Another day, another Route 28 crash. The road's consistency is truly admirable.",
        "Route 28 crashes have become so frequent, they're now classified as a renewable resource.",
        "Emergency services have installed a Route 28 crash hotline. It's just a recording that says 'We know.'",
        "Forget Netflix and chill, I'm just here for the live-action crash replays on Route 28.",
        "Route 28: Where GPS says 'In 500 feet, prepare to question all your life choices.'",
        "Heard a new band is forming: 'Route 28 & The Fender Benders.'",
    ]

    # Filter out recently used prompts
    available_prompts = [p for p in prompts if p not in recent_prompts]

    # If all prompts have been used recently, use all prompts
    if not available_prompts:
        available_prompts = prompts
        logging.info(
            f"All prompts used recently (last {len(recent_prompts)}). Using all prompts for selection."
        )

    intro = random.choice(available_prompts)
    logging.info(
        f"Selected prompt: '{intro}' (avoiding last {len(recent_prompts)} prompts)"
    )

    lat = alert["latitude"]
    lon = alert["longitude"]
    utc_time = alert.get("publish_datetime_utc")
    if utc_time:
        try:
            # Use .%fZ for robustness with Waze timestamps
            dt = datetime.strptime(utc_time, "%Y-%m-%dT%H:%M:%S.%fZ")
            timestamp = (
                dt.replace(tzinfo=ZoneInfo("UTC"))
                .astimezone(ZoneInfo("America/New_York"))
                .strftime("%-I:%M %p on %b %d")
            )
        except ValueError:
            timestamp = "Unknown time (parse error)"
    else:
        timestamp = "Unknown time"
    street = alert.get("street") or "an unknown street"
    city = get_city_name(lat, lon)
    # Ensure embed_url uses a valid URL format for consistency (example from plane_tracker)
    Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    # Emojis are here and untouched
    formatted_message_text = f"🚨 {intro}\n\n📍 Location: Near {street} in {city}.\n🕒 Reported at: {timestamp}\n#Route28 #Pittsburgh #Traffic #PennDOT"
    return intro, formatted_message_text, Maps_url, f"Near {street} in {city}"


# MODIFIED post_to_bluesky function to handle local image embeds
def post_to_bluesky(
    text,
    embed_url=None,
    embed_title=None,
    embed_description=None,
    local_image_path=None,
    max_retries=3,
):
    """
    Post to Bluesky with retry logic, supporting external link embeds OR a single local image/GIF embed.

    Args:
        text: Post content
        embed_url: Optional URL for an external link embed.
        embed_title: Optional title for the external link embed.
        embed_description: Optional description for the external link embed.
        local_image_path: Optional path to a local image/GIF file to embed.
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        bool: True if successful, False if all retries failed
    """
    for attempt in range(max_retries + 1):
        try:
            client = Client()
            client.login(BLSKY_HANDLE, BLSKY_APP_PASSWORD)

            main_embed = None

            # Handle local image/GIF embed if path is provided
            if local_image_path:
                try:
                    with open(local_image_path, "rb") as f:
                        img_bytes = f.read()

                    # Determine MIME type based on file extension
                    if local_image_path.lower().endswith((".png", ".jpg", ".jpeg")):
                        mime_type = "image/jpeg"
                        if local_image_path.lower().endswith(".png"):
                            mime_type = "image/png"
                    elif local_image_path.lower().endswith(".gif"):
                        mime_type = "image/gif"
                    else:
                        logging.warning(
                            f"Could not determine MIME type for {local_image_path}. Defaulting to image/jpeg."
                        )
                        mime_type = "image/jpeg"

                    logging.info(
                        f"Uploading local image/GIF from {local_image_path} to Bluesky..."
                    )
                    upload_response = client.upload_blob(img_bytes, mime_type)

                    main_embed = models.AppBskyEmbedImages.Main(
                        images=[
                            models.AppBskyEmbedImages.Image(
                                image=upload_response,
                                alt="The Count from Sesame Street counting crashes",  # Mandatory alt text
                            )
                        ]
                    )
                    logging.info(
                        f"Local image/GIF blob uploaded successfully for {local_image_path}."
                    )

                except FileNotFoundError:
                    logging.error(
                        f"Local image file not found: {local_image_path}. Skipping image embed."
                    )
                except Exception as e:
                    logging.error(
                        f"Error during local image/GIF upload for {local_image_path}: {e}. Skipping image embed."
                    )

            # If no image embed was created (or failed), try external link embed
            if not main_embed and embed_url:
                main_embed = models.AppBskyEmbedExternal.Main(
                    external=models.AppBskyEmbedExternal.External(
                        uri=embed_url,
                        title=embed_title or "View on Google Maps",
                        description=embed_description
                        or "Click to view location on Google Maps",
                    )
                )

            client.send_post(text, embed=main_embed)

            if attempt > 0:
                logging.info(
                    f"Successfully posted to Bluesky on attempt {attempt + 1}/{max_retries + 1}."
                )
            else:
                logging.info("Successfully posted to Bluesky.")
            return True

        except Exception as e:
            if attempt < max_retries:
                wait_time = 2**attempt
                logging.warning(
                    f"Bluesky post attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {wait_time} seconds..."
                )
                time.sleep(wait_time)
            else:
                logging.error(
                    f"All {max_retries + 1} Bluesky post attempts failed. Final error: {e}"
                )
                return False

    return False  # Should never reach here, but safety fallback


def post_to_x(
    text,
    embed_url=None,
    embed_title=None,
    embed_description=None,
    local_image_path=None,
    max_retries=3,
):
    """
    Post to X.com (Twitter) with retry logic, supporting external link embeds OR a single local image/GIF embed.

    Args:
        text: Post content
        embed_url: Optional URL for an external link embed.
        embed_title: Optional title for the external link embed.
        embed_description: Optional description for the external link embed.
        local_image_path: Optional path to a local image/GIF file to embed.
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        bool: True if successful, False if all retries failed
    """
    if not TWEEPY_AVAILABLE:
        logging.error("tweepy not available. Cannot post to X.com.")
        return False

    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        logging.error("Missing X.com API credentials. Cannot post to X.com.")
        return False

    for attempt in range(max_retries + 1):
        try:
            # Initialize X.com API client
            auth = tweepy.OAuthHandler(X_API_KEY, X_API_SECRET)
            auth.set_access_token(X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)
            api = tweepy.API(auth, wait_on_rate_limit=True)

            # Handle local image/GIF embed if path is provided
            if local_image_path:
                try:
                    logging.info(
                        f"Uploading local image/GIF from {local_image_path} to X.com..."
                    )
                    media = api.media_upload(local_image_path)
                    api.update_status(text, media_ids=[media.media_id])
                    logging.info(
                        f"Local image/GIF uploaded successfully for {local_image_path}."
                    )
                except FileNotFoundError:
                    logging.error(
                        f"Local image file not found: {local_image_path}. Skipping image embed."
                    )
                    # Post without image
                    api.update_status(text)
                except Exception as e:
                    logging.error(
                        f"Error during local image/GIF upload for {local_image_path}: {e}. Skipping image embed."
                    )
                    # Post without image
                    api.update_status(text)
            else:
                # Post text only or with URL (X.com automatically embeds URLs)
                if embed_url:
                    # Include the URL in the text for automatic embedding
                    post_text = f"{text}\n\n{embed_url}"
                else:
                    post_text = text

                api.update_status(post_text)

            if attempt > 0:
                logging.info(
                    f"Successfully posted to X.com on attempt {attempt + 1}/{max_retries + 1}."
                )
            else:
                logging.info("Successfully posted to X.com.")
            return True

        except Exception as e:
            if attempt < max_retries:
                wait_time = 2**attempt
                logging.warning(
                    f"X.com post attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {wait_time} seconds..."
                )
                time.sleep(wait_time)
            else:
                logging.error(
                    f"All {max_retries + 1} X.com post attempts failed. Final error: {e}"
                )
                return False

    return False  # Should never reach here, but safety fallback


def post_to_social_media(
    text,
    embed_url=None,
    embed_title=None,
    embed_description=None,
    local_image_path=None,
    max_retries=3,
):
    """
    Universal posting function that routes to the appropriate platform based on POSTING_PLATFORM setting.

    Args:
        text: Post content
        embed_url: Optional URL for an external link embed.
        embed_title: Optional title for the external link embed.
        embed_description: Optional description for the external link embed.
        local_image_path: Optional path to a local image/GIF file to embed.
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        bool: True if successful, False if all retries failed
    """
    if POSTING_PLATFORM == "x":
        return post_to_x(
            text,
            embed_url,
            embed_title,
            embed_description,
            local_image_path,
            max_retries,
        )
    elif POSTING_PLATFORM == "bluesky":
        return post_to_bluesky(
            text,
            embed_url,
            embed_title,
            embed_description,
            local_image_path,
            max_retries,
        )
    else:
        logging.error(
            f"Unknown posting platform: {POSTING_PLATFORM}. Supported platforms: 'bluesky', 'x'"
        )
        return False


# --- NEW MONTHLY COUNTER FUNCTIONS ---
def load_monthly_crash_data():
    """Loads the monthly crash data from a JSON file.
    If the file is not found, it initializes and SAVES default data.
    """
    try:
        with open(MONTHLY_CRASH_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.info(
            f"'{MONTHLY_CRASH_FILE}' not found. Initializing and creating with default data."
        )
        default_data = {
            "current_month_crashes": 0,
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            with open(MONTHLY_CRASH_FILE, "w") as f:
                json.dump(default_data, f, indent=2)
            logging.info(
                f"'{MONTHLY_CRASH_FILE}' successfully created with initial data."
            )
        except IOError as e:
            logging.critical(
                f"Critical: Failed to create and save '{MONTHLY_CRASH_FILE}': {e}. Proceeding with in-memory default data."
            )
        return default_data
    except json.JSONDecodeError:
        logging.error(
            f"Error decoding JSON from '{MONTHLY_CRASH_FILE}'. Re-initializing and saving default data."
        )
        default_data = {
            "current_month_crashes": 0,
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            with open(MONTHLY_CRASH_FILE, "w") as f:
                json.dump(default_data, f, indent=2)
            logging.info(
                f"'{MONTHLY_CRASH_FILE}' overwritten with default data due to corruption."
            )
        except IOError as e:
            logging.critical(
                f"Critical: Failed to save '{MONTHLY_CRASH_FILE}' after decode error: {e}. Proceeding with in-memory default data."
            )
        return default_data
    except IOError as e:
        logging.critical(
            f"Permission error or other I/O error reading '{MONTHLY_CRASH_FILE}': {e}. Cannot load monthly crash data. Proceeding with in-memory default data."
        )
        return {
            "current_month_crashes": 0,
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
        }


def save_monthly_crash_data(data):
    """Saves the monthly crash data to a JSON file."""
    try:
        with open(MONTHLY_CRASH_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logging.error(f"Error saving monthly crash data to '{MONTHLY_CRASH_FILE}': {e}")


def increment_monthly_counter():
    """Increments the monthly crash counter."""
    data = load_monthly_crash_data()
    data["current_month_crashes"] += 1
    save_monthly_crash_data(data)
    logging.info(
        f"Monthly crash counter incremented. Current count: {data['current_month_crashes']}"
    )


def handle_monthly_reset_and_report():
    """
    Checks if it's the end of the month and handles reporting and resetting.
    This function should be called daily (e.g., via cron) or at the start of your script.
    """
    data = load_monthly_crash_data()

    current_date = datetime.now()
    last_reset_dt = datetime.strptime(data["last_reset_date"], "%Y-%m-%d")

    next_month = current_date.replace(day=28) + timedelta(days=4)
    last_day_of_current_month = next_month - timedelta(days=next_month.day)

    target_time_check = current_date.replace(
        hour=12, minute=59, second=0, microsecond=0
    )

    is_end_of_month_and_time = (
        current_date.day == last_day_of_current_month.day
        and current_date >= target_time_check
        and current_date.month != last_reset_dt.month
    )

    is_start_of_new_month = (
        current_date.day == 1 and current_date.month != last_reset_dt.month
    )

    if is_end_of_month_and_time or is_start_of_new_month:
        reported_month_dt = (
            current_date - timedelta(days=1) if is_start_of_new_month else current_date
        )
        reported_month_name = reported_month_dt.strftime("%B")
        reported_year = reported_month_dt.year

        total_crashes_last_month = data["current_month_crashes"]

        report_message = (
            f"🚗 Monthly Crash Report for {reported_month_name} {reported_year}:\n"
            f"There were {total_crashes_last_month} car crashes detected on or near Route 28 in {reported_month_name}.\n"
            "#Pittsburgh #Traffic #Route28 #PennDOT #MonthlyReport"
        )
        logging.info(f"Attempting to post monthly report: {report_message}")

        # MODIFIED CALL TO post_to_social_media for GIF embed
        post_successful = post_to_social_media(
            report_message,
            embed_title="Monthly Route 28 Crash Report",
            local_image_path=MONTHLY_REPORT_GIF_PATH,  # ADDED THIS LINE
        )

        if post_successful:
            logging.info(
                f"Monthly crash report for {reported_month_name} posted successfully."
            )
            data["current_month_crashes"] = 0
            data["last_reset_date"] = current_date.strftime("%Y-%m-%d")
            save_monthly_crash_data(data)
            logging.info("Monthly crash counter reset to 0.")
        else:
            logging.error("Failed to post monthly crash report to Bluesky.")
    else:
        logging.info(
            "Not the end of the month for reporting/resetting or already processed for this month."
        )


def check_route_28():
    initial_seen_crashes_raw = load_seen_data(SEEN_FILE)

    initial_seen_crashes_clean = []
    for crash in initial_seen_crashes_raw:
        if all(k in crash for k in ["alert_id", "publish_datetime_utc", "lat", "lon"]):
            initial_seen_crashes_clean.append(crash)
        else:
            logging.warning(
                f"Malformed crash entry found in {SEEN_FILE} on load: {crash}. Skipping this entry."
            )

    seen_crashes_current_session = purge_old_crashes(initial_seen_crashes_clean)

    for i, box in enumerate(ROUTE28_BOXES):
        required_keys = ["bottom", "top", "left", "right"]
        if not all(key in box for key in required_keys):
            logging.critical(
                f"Malformed bounding box found at index {i} in ROUTE28_BOXES. Missing one or more of {required_keys}. Exiting."
            )
            sys.exit(1)

    recent_prompts = load_last_prompts(LAST_PROMPTS_FILE)
    new_alerts_posted_this_run = False

    current_run_processed_alert_ids = set()

    for box in ROUTE28_BOXES:
        alerts = get_waze_alerts(box)
        logging.info(f"Total alerts received for this box: {len(alerts)}")
        for alert in alerts:
            alert_id = alert.get("alert_id")
            publish_time_utc = alert.get("publish_datetime_utc")

            if not alert_id or not publish_time_utc:
                logging.warning(
                    f"Skipping alert due to missing fields: {json.dumps(alert)}"
                )
                continue

            if alert.get("type") == "ACCIDENT":
                street = alert.get("street") or ""
                if (
                    re.search(
                        r"\b(ROUTE|RT|US|STATE ROUTE|PA)[ -]?28\b",
                        street,
                        re.IGNORECASE,
                    )
                    or (
                        "28" in street
                        and "228" not in street
                        and "128" not in street
                        and "328" not in street
                        and "428" not in street
                        and "528" not in street
                    )
                ) and ("BUS" not in street.upper()):

                    if alert_id in current_run_processed_alert_ids:
                        logging.info(
                            f"Alert {alert_id} already processed in this run. Skipping."
                        )
                        continue

                    if is_duplicate_incident(alert, seen_crashes_current_session):
                        logging.info(
                            f"Alert {alert_id} skipped due to being a recent duplicate (historically seen)."
                        )
                        current_run_processed_alert_ids.add(alert_id)
                        continue

                    chosen_prompt, post_text, Maps_url, embed_desc = format_alert(
                        alert, recent_prompts
                    )
                    logging.info(
                        f"Attempting to post new alert {alert_id} to {POSTING_PLATFORM.upper()} with prompt: '{chosen_prompt}'."
                    )

                    # Original call to post_to_social_media for daily reports (NO GIF)
                    post_successful = post_to_social_media(
                        post_text,
                        embed_url=Maps_url,
                        embed_title="View Crash Location",
                        embed_description=embed_desc,
                    )

                    if post_successful:
                        # Increment the monthly crash counter
                        increment_monthly_counter()

                        # Update recent prompts list
                        recent_prompts = add_prompt_to_history(
                            chosen_prompt, recent_prompts
                        )
                        save_last_prompts(recent_prompts, LAST_PROMPTS_FILE)

                        seen_crashes_current_session.append(
                            {
                                "alert_id": alert_id,
                                "publish_datetime_utc": publish_time_utc,
                                "lat": alert["latitude"],
                                "lon": alert["longitude"],
                            }
                        )
                        new_alerts_posted_this_run = True
                    else:
                        logging.error(
                            f"Bluesky post failed for alert {alert_id}. Not saving to seen_crashes to allow re-attempt later."
                        )

                    current_run_processed_alert_ids.add(alert_id)

    successful_posts = sum(
        1
        for crash in seen_crashes_current_session
        if crash not in initial_seen_crashes_clean
    )
    logging.info(
        f"Processing summary: {len(current_run_processed_alert_ids)} alerts processed, {successful_posts} successfully posted this run"
    )
    initial_set_of_crashes = {frozenset(d.items()) for d in initial_seen_crashes_clean}
    final_set_of_crashes = {frozenset(d.items()) for d in seen_crashes_current_session}

    if initial_set_of_crashes != final_set_of_crashes:
        save_seen_data(seen_crashes_current_session, SEEN_FILE)
        logging.info(
            f"Updated {SEEN_FILE} with {len(seen_crashes_current_session)} entries."
        )
    else:
        logging.info(f"No updates to {SEEN_FILE}.")


if __name__ == "__main__":
    logging.info(f"Script started at {datetime.now()}")

    # Validate credentials based on selected platform
    if POSTING_PLATFORM == "bluesky":
        if not all([BLSKY_HANDLE, BLSKY_APP_PASSWORD, RAPIDAPI_KEY]):
            logging.critical("Missing Bluesky credentials in .env file. Exiting.")
            sys.exit(1)
    elif POSTING_PLATFORM == "x":
        if not all(
            [
                X_API_KEY,
                X_API_SECRET,
                X_ACCESS_TOKEN,
                X_ACCESS_TOKEN_SECRET,
                RAPIDAPI_KEY,
            ]
        ):
            logging.critical("Missing X.com API credentials in .env file. Exiting.")
            sys.exit(1)
        if not TWEEPY_AVAILABLE:
            logging.critical(
                "tweepy library not available. Install with: pip install tweepy. Exiting."
            )
            sys.exit(1)
    else:
        logging.critical(
            f"Unknown posting platform: {POSTING_PLATFORM}. Supported platforms: 'bluesky', 'x'. Exiting."
        )
        sys.exit(1)

    if not RAPIDAPI_KEY:
        logging.critical("Missing RAPIDAPI_KEY in .env file. Exiting.")
        sys.exit(1)

    logging.info(f"Using posting platform: {POSTING_PLATFORM}")

    # Check and handle monthly reset/report BEFORE checking for new crashes
    handle_monthly_reset_and_report()
    check_route_28()
    logging.info(f"Script finished at {datetime.now()}")
