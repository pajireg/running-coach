import os
import json
from datetime import date
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

TOKEN_DIR = os.path.abspath(".garmin_tokens")
os.environ["GARMINTOKENS"] = TOKEN_DIR

def main():
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    garmin = Garmin(email, password)
    garmin.login()

    print("--- Inspecting Training Plans ---")
    try:
        plans = garmin.get_training_plans()
        print(f"Total Plans Found: {len(plans)}")
        print(json.dumps(plans, indent=2)[:2000]) # Print snippet
    except Exception as e:
        print(f"Error fetching plans: {e}")

if __name__ == "__main__":
    main()
