# 가민의 공식 '훈련 계획(Training Plans)' 데이터를 검사하기 위한 스크립트
# (가민 코치 등 공식 플랜의 구조를 분석할 때 사용함)
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

    print("--- 가민 훈련 계획(Training Plans) 검사 중 ---")
    try:
        plans = garmin.get_training_plans()
        print(f"총 {len(plans)}개의 계획을 찾았습니다.")
        print(json.dumps(plans, indent=2)[:2000]) # Print snippet
    except Exception as e:
        print(f"Error fetching plans: {e}")

if __name__ == "__main__":
    main()
