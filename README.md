# Route 28 Crash Tracker 🚨

A Python script that monitors Route 28 in Pittsburgh, Pennsylvania for traffic accidents using Waze data and automatically posts alerts to Bluesky social media platform.

## Features

- **Real-time monitoring**: Tracks accidents specifically on Route 28 using Waze traffic data
- **Duplicate prevention**: Filters out duplicate incidents within 1km and 60 minutes
- **Automatic posting**: Posts crash alerts to Bluesky with location details and Google Maps links
- **Intelligent messaging**: Rotates through humorous prompts to avoid repetitive posts
- **Data persistence**: Maintains crash history and avoids reposting old incidents
- **Geocoding**: Resolves crash locations to city names for better context

## Requirements

### Python Dependencies
```bash
pip install requests atproto geopy python-dotenv
```

### API Keys & Accounts

1. **Waze Data API** (via RapidAPI):
   - Sign up at [RapidAPI](https://rapidapi.com/)
   - Subscribe to the [Waze API](https://rapidapi.com/apidojo/api/waze/) from ADSBexchange
   - **Note**: You need to purchase a package of API calls. Each script run = 1 API call
   - Get your `X-RapidAPI-Key`

2. **Bluesky Account**:
   - Create a Bluesky account at [bsky.app](https://bsky.app)
   - Generate an App Password in your account settings

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd route28-crash-tracker
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root:
```env
BLUESKY_HANDLE=your-bluesky-handle.bsky.social
BLUESKY_APP_PASSWORD=your-app-password
RAPIDAPI_KEY=your-rapidapi-key
```

## Configuration

### Route 28 Coverage Area
The script monitors crashes within this bounding box:
- **Latitude**: 40.450 to 40.700
- **Longitude**: -80.050 to -79.600

### Duplicate Detection Settings
- **Distance threshold**: 1km (crashes closer than this are considered duplicates)
- **Time threshold**: 60 minutes (crashes within this timeframe are compared)
- **Data retention**: 24 hours (older crashes are purged from tracking)

## Usage

### Manual Execution
```bash
python crash.py
```

### Automated Execution (Recommended)
Set up a cron job to run every 5-10 minutes:

```bash
# Edit crontab
crontab -e

# Add this line to check every 5 minutes
*/5 * * * * /path/to/python /path/to/crash.py

# Or every 10 minutes to reduce API usage
*/10 * * * * /path/to/python /path/to/crash.py
```

## How It Works

1. **Data Collection**: Queries Waze API for accident alerts in the Route 28 area
2. **Filtering**: Identifies crashes specifically on Route 28 (excludes Route 228)
3. **Duplicate Check**: Compares new alerts against recent crashes to avoid duplicates
4. **Geocoding**: Resolves coordinates to city names using Nominatim
5. **Posting**: Formats and posts crash alerts to Bluesky with embedded Google Maps links
6. **Logging**: Maintains detailed logs of all activities

## Output Files

- `seen_crashes.json`: Stores processed crash data to prevent duplicates
- `last_prompt.json`: Tracks the last used prompt to ensure variety
- `route28_watcher.log`: Detailed logging of all script activities

## Sample Output

```
🚨 Reset the 'Days Since Last Crash on Route 28' counter to zero.

📍 Location: Near Route 28 in Millvale
🕒 Reported at: 2:45 PM on Jan 15
#Route28 #Pittsburgh #Traffic
```

## Cost Considerations

- **API Calls**: Each script execution = 1 API call to Waze
- **Recommended frequency**: Every 5-10 minutes during peak hours
- **Daily usage**: ~144-288 API calls per day (depending on frequency)
- **Monthly estimate**: ~4,320-8,640 API calls per month

Make sure to purchase an appropriate API call package from RapidAPI based on your intended usage frequency.

## Troubleshooting

### Common Issues

1. **Missing API credentials**: Ensure `.env` file contains all required keys
2. **API rate limits**: Reduce execution frequency if hitting limits
3. **Geocoding failures**: Script continues with "unknown" city names
4. **Duplicate posts**: Check if `seen_crashes.json` is being saved properly

### Logging

Check `route28_watcher.log` for detailed information about:
- API requests and responses
- Duplicate detection results
- Posting success/failure
- Error messages

## License

This project is open source. Please use responsibly and in accordance with the APIs' terms of service.

## Contributing

Feel free to submit issues and pull requests to improve the script's functionality or coverage area.

## Disclaimer

This script is for informational purposes only. Always follow official traffic reports and local authorities for the most accurate and up-to-date traffic information.