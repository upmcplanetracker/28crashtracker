# Another Route 28 Crash?!?! tracker

## 🚀 Overview

This Python script, "Another Route 28 Crash?!?! tracker," is designed to monitor traffic incident data, specifically looking for accident reports on Route 28 in the Pittsburgh, PA area. When a new, unique accident on Route 28 is detected, the script automatically posts an alert to a specified Bluesky account. It helps keep track of those all-too-frequent incidents on a notorious stretch of road!

You can find the script directly at: [https://github.com/upmcplanetracker/28crashtracker/blob/main/crash.py](https://github.com/upmcplanetracker/28crashtracker/blob/main/crash.py)

## ✨ Features

* **Waze Integration:** Fetches real-time accident data using the Waze RapidAPI.

* **Route 28 Specific:** Filters incidents to focus solely on Route 28 within a predefined geographical bounding box.

* **Duplicate Prevention:** Intelligently identifies and skips duplicate or very recent re-reports of the same incident, based on proximity and time, to avoid spamming.

* **Bluesky Integration:** Posts new accident alerts to a Bluesky account with a randomly selected, engaging message.

* **Persistent Tracking:** Uses `seen_crashes.json` to keep track of previously reported incidents and `last_prompt.json` to vary post intros.

* **Logging:** Provides detailed logging to both a file (`route28_watcher.log`) and the console for monitoring.

* **Configurable:** Easily adjust parameters like duplicate detection thresholds and data purging intervals.

## 🛠️ Prerequisites

Before you run this script, ensure you have:

* **Python 3.9+**: Required for `zoneinfo`.

* **Bluesky Account**: You'll need your Bluesky handle and an [App Password](https://bsky.social/settings/app-passwords) generated from your Bluesky account settings. **Do not use your main account password.**

* **RapidAPI Key**: You'll need an API key from [RapidAPI](https://rapidapi.com/) to access the Waze API endpoint. You can search for "Waze" or "Traffic Alerts" on RapidAPI to find a suitable endpoint.

## 💻 Installation

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/upmcplanetracker/28crashtracker.git](https://github.com/upmcplanetracker/28crashtracker.git)
    cd 28crashtracker
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: `venv\Scripts\activate`
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    If you don't have a `requirements.txt` file, you can create one with the following contents and then run `pip install -r requirements.txt`:

    ```
    requests
    atproto
    geopy
    python-dotenv
    ```

## 🔑 Configuration (`.env` file)

This script uses environment variables for sensitive credentials. You need to create a file named `.env` in the same directory as your `crash.py` script.

**Create a `.env` file with the following content:**

```dotenv
BLUESKY_HANDLE="yourblueskyhandle.bsky.social"
BLUESKY_APP_PASSWORD="yourblueskyapppassword"
RAPIDAPI_KEY="yourwazerapidapikey"
```

**Replace the placeholder values:**

* `BLUESKY_HANDLE`: Your full Bluesky handle (e.g., `"@yourhandle.bsky.social"`).

* `BLUESKY_APP_PASSWORD`: The specific app password you generated in your Bluesky account settings.

* `RAPIDAPI_KEY`: Your API key obtained from RapidAPI for the Waze API.

## ⚠️ API Usage and Costs

Each time this script runs, it makes **two API calls** to RapidAPI's Waze endpoint.

Please be aware of the RapidAPI Waze API's free tier limitations:

* The free tier typically provides **50 free calls per month**.

* If you plan to run this script frequently (e.g., every 5 minutes), you will quickly exceed the free tier. For instance, running every 5 minutes for a month would consume `(60 minutes / 5 minutes) * 24 hours * 30 days * 2 calls/run = 17,280 calls`.

* To get a higher call limit (e.g., 10,000 calls per month), you will likely need to subscribe to a basic plan, which might cost around **$25 per month**. Check the specific pricing details on the RapidAPI Waze endpoint page.

## 🚀 Usage

Once you have installed the dependencies and configured your `.env` file, you can run the script:

```bash
python crash.py
```

The script will fetch Waze alerts, process them, and post to Bluesky if a new Route 28 accident is found. It will also log its activity to `route28_watcher.log` and the console.

### Running Periodically with Cron (Linux/macOS)

To automate the script to run at regular intervals (e.g., every 5 minutes), you can use `cron`.

1.  **Open your crontab for editing:**
    ```bash
    crontab -e
    ```
    (If this is your first time, it might ask you to choose a text editor.)

2.  **Add the cron job entry:**
    Add the following line to the end of the file. Make sure to replace `/path/to/your/project/` with the actual absolute path to your `28crashtracker` directory.

    ```cron
    */5 * * * * /usr/bin/python3 /path/to/your/project/28crashtracker/crash.py >> /path/to/your/project/28crashtracker/cron.log 2>&1
    ```

    **Explanation of the cron entry:**
    * `*/5 * * * *`: This is the schedule. It means "at every 5th minute" (e.g., 00:05, 00:10, 00:15, etc.).
        * `*`: Any minute (0-59)
        * `*`: Any hour (0-23)
        * `*`: Any day of the month (1-31)
        * `*`: Any month (1-12)
        * `*`: Any day of the week (0-7, Sunday is 0 or 7)
    * `/usr/bin/python3`: This is the absolute path to your Python 3 executable. You might need to adjust this. You can find it by running `which python3` in your terminal.
    * `/path/to/your/project/28crashtracker/crash.py`: This is the absolute path to your `crash.py` script. **Ensure this path is correct.**
    * `>> /path/to/your/project/28crashtracker/cron.log 2>&1`: This redirects all standard output and standard error from the script to a file named `cron.log` within your project directory. This is crucial for debugging cron jobs, as they don't have a visible console.

3.  **Save and Exit:**
    * If using `nano` (common default): Press `Ctrl+X`, then `Y` to confirm save, then `Enter`.
    * If using `vi`/`vim`: Press `Esc`, then type `:wq` and press `Enter`.

Your cron job is now scheduled! The script will run automatically at the specified intervals.

## 📄 Log Files

The script generates:

* `route28_watcher.log`: A detailed log of script activity.

* `seen_crashes.json`: Stores a list of recently seen unique crash incidents to prevent duplicate posts.

* `last_prompt.json`: Stores the last used introductory prompt for a Bluesky post to ensure variety.

## 🤝 Contributing

Feel free to fork the repository, make improvements, and submit pull requests!

## 📜 License

This project is licensed under the **GNU General Public License v3.0**. See the [LICENSE file](https://github.com/upmcplanetracker/28crashtracker/blob/main/LICENSE) for more details.
