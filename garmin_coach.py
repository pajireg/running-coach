import os
import json
import time
from datetime import date, timedelta
from dotenv import load_dotenv
from garminconnect import Garmin
from google import genai
from google.genai import types

# 환경 변수 로드
load_dotenv()

# 가민 토큰 경로 설정
TOKEN_DIR = os.path.abspath(".garmin_tokens")
os.environ["GARMINTOKENS"] = TOKEN_DIR

def login_to_garmin():
    """가민 커넥트 로그인 (환경 변수와 저장된 토큰 사용)"""
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    
    if not email or not password:
        print("에러: .env 파일에서 GARMIN_EMAIL 또는 GARMIN_PASSWORD를 찾을 수 없음")
        return None

    if not os.path.exists(TOKEN_DIR):
        print(f"경고: 토큰 디렉토리 '{TOKEN_DIR}'가 없음")
        print("인증을 위해 'python setup_garmin.py'를 먼저 실행해야 함")

    try:
        garmin = Garmin(email, password)
        garmin.login()
        print("로그인 성공!")
        return garmin
    except Exception as e:
        print(f"로그인 실패: {e}")
        return None

def get_advanced_metrics(garmin):
    """상세 건강 및 퍼포먼스 지표 가져오기"""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    print("상세 건강 및 퍼포먼스 데이터 수집 중...")

    # 1. 기본 통계
    try:
        stats = garmin.get_user_summary(today)
    except: stats = {}
    
    # 2. 바디 배터리
    try:
        bb_data = garmin.get_body_battery(today)
        bb_val = "알 수 없음"
        if bb_data and isinstance(bb_data, list):
            last_entry = bb_data[-1]
            if 'bodyBatteryValuesArray' in last_entry:
                values = last_entry['bodyBatteryValuesArray']
                if values: bb_val = values[-1][1]
    except: bb_val = "알 수 없음"

    # 3. 개인 기록 (PR)
    try:
        prs = garmin.get_personal_record()
    except: prs = {}

    # 4. 훈련 상태 및 부하
    try:
        status = garmin.get_training_status(today)
    except: status = {}

    # 5. 젖산 역치
    try:
        threshold = garmin.get_lactate_threshold(yesterday, today)
    except: threshold = {}

    # 6. HRV (심박 변이도)
    try:
        hrv = garmin.get_hrv_data(today)
    except: hrv = {}

    # 7. 어제 활동 내역
    try:
        yesterday_acts = garmin.get_activities_by_date(yesterday, yesterday)
        actual_yesterday = []
        for act in yesterday_acts:
            actual_yesterday.append({
                "name": act.get("activityName"),
                "type": act.get("activityType", {}).get("typeKey"),
                "distance": act.get("distance"),
                "duration": act.get("duration"),
                "calories": act.get("calories")
            })
    except: actual_yesterday = []

    # 8. 기존 일정 (컨텍스트 파악용)
    try:
        year = date.today().year
        month = date.today().month - 1
        url = f"/calendar-service/year/{year}/month/{month}"
        resp = garmin.garth.get("connectapi", url, api=True)
        cal_data = resp.json()
        existing_plan = []
        for item in cal_data.get("calendarItems", []):
            if item.get("itemType") == "workout":
                existing_plan.append({
                    "date": item.get("date"),
                    "title": item.get("title")
                })
    except: existing_plan = []

    return {
        "date": today,
        "health": {
            "steps": stats.get("totalSteps"),
            "sleepScore": stats.get("sleepScore"),
            "restingHR": stats.get("restingHeartRate"),
            "bodyBattery": bb_val,
            "hrv": hrv.get("lastNightAvg") if hrv else "알 수 없음"
        },
        "performance": {
            "prs": prs,
            "trainingStatus": status.get("trainingStatus"),
            "vo2Max": status.get("vo2Max"),
            "lactateThreshold": threshold
        },
        "context": {
            "yesterday_actual": actual_yesterday,
            "current_schedule": existing_plan
        }
    }

def pace_to_ms(pace_str, margin=0):
    """'MM:SS' 형식의 km당 페이스를 m/s(초당 미터)로 변환. margin(초)을 더하거나 뺄 수 있음."""
    try:
        if not pace_str: return 0
        import re
        # MM:SS 패턴 추출
        match = re.search(r'(\d+):(\d+)', str(pace_str))
        if not match: return 0
        
        minutes, seconds = map(int, match.groups())
        total_seconds_per_km = minutes * 60 + seconds + margin
        
        # 0보다 작아지지 않게 방지 (매우 빠른 페이스 방지)
        if total_seconds_per_km <= 0: return 0
        
        return 1000 / total_seconds_per_km
    except:
        return 0

def ask_gemini_for_plan(metrics, include_strength=False, race_date=None, race_distance=None, race_goal_time=None, race_target_pace=None):
    """지표 및 대회 구체적 목표를 기반으로 Gemini에게 7일치 훈련 계획 요청"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("에러: GEMINI_API_KEY를 찾을 수 없음")
        return None
        
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are an elite running coach. Based on the user's Garmin data, create a **7-day training plan** starting today ({metrics['date']}).
    
    USER DATA:
    - Recent Health: {json.dumps(metrics['health'])}
    - Performance: {json.dumps(metrics['performance'])}
    - Context (Yesterday Actual vs Planned): {json.dumps(metrics['context'])}
    
    RACE CONTEXT:
    {"- RACE DATE: " + race_date if race_date else "- No specific race date."}
    {"- RACE DISTANCE: " + race_distance if race_distance else "- No specific distance (Focus on overall fitness)."}
    {"- GOAL TIME: " + race_goal_time if race_goal_time else ""}
    {"- TARGET PACE: " + race_target_pace if race_target_pace else ""}
    
    COACHING RULES:
    1. ADAPTIVE PLANNING: 
       - Look at 'yesterday_actual' in context. If the user skipped a planned workout or did extra, adjust TODAY and the rest of the week accordingly.
       - If they are over-trained (high load, low HRV), prioritize recovery/rest.
    2. SPORT TYPE:
       - **ONLY RUNNING workouts are allowed.**
       - {"Include strength training only if it complements the running plan." if include_strength else "STRICTLY RUNNING ONLY. Use 'Rest' for non-running days."}
    3. PERIODIZATION & VOLUME:
       - {"If a race is set: Calculate weeks until race. Adjust total weekly volume and long run distance based on RACE DISTANCE (" + race_distance + ") and proximity to RACE DATE." if race_date else "- Maintain a balanced mix of base runs, recovery, and one hard session."}
    4. PACE & TARGETS: 
       {"- If GOAL TIME (" + race_goal_time + ") is set for DISTANCE (" + race_distance + "), calculate the required target pace. Use this pace for race-specific intervals." if race_goal_time and race_distance else ""}
       - Calculate training zones based on PRs and Lactate Threshold.
       - Use 'speed' target type for runs.
    5. Weekend: One "Long Run" (Saturday or Sunday).
    6. Mid-week: One "Interval" or "Tempo" session.
    7. RATIONALE (Korean): For each workout, provide a brief rationale in Korean in the 'description' field, explaining how it helps with the specific RACE GOAL or general fitness.
    
    OUTPUT FORMAT:
    Return a JSON object with a key 'plan' containing a list of 7 days.
    Each day should have:
    {{
      "date": "YYYY-MM-DD",
      "workout": {{
        "workoutName": "Coach Gemini: [Day Type]",
        "description": "Short explanation in Korean",
        "sportType": "RUNNING",
        "steps": [
          {{
            "type": "Warmup|Run|Interval|Recovery|Cooldown",
            "durationValue": [seconds],
            "durationUnit": "second",
            "targetType": "no_target|speed",
            "targetValue": "MM:SS" (pace per km)
          }}
        ]
      }}
    }}
    
    Return ONLY valid JSON.
    """
    
    print("Gemini로 7일 훈련 계획 생성 중...")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e):
                print(f"API 할당량 초과. 45초 후 재시도... ({attempt+1}/3)")
                time.sleep(45)
            else:
                print(f"Gemini API 에러: {e}")
                return None
    return None

from garminconnect.workout import (
    RunningWorkout, 
    WorkoutSegment, 
    ExecutableStep, 
    SportType, 
    StepType, 
    ConditionType, 
    TargetType,
    SportTypeModel,
    EndConditionModel,
    TargetTypeModel
)

def create_garmin_workout(garmin, workout_json):
    """가민 커넥트에 워크아웃 업로드 (객체 모델 사용)"""
    if not workout_json: return None

    name = workout_json.get('workoutName', 'Gemini Workout')
    print(f"워크아웃 생성 중: {name}")

    try:
        steps = workout_json.get("steps", [])
        executable_steps = []
        total_duration = 0
        
        for i, step in enumerate(steps):
            order = i + 1
            duration_val = float(step.get("durationValue", 0))
            step_type_str = step.get("type", "Run")
            target_type_str = step.get("targetType", "no_target")
            target_val_str = step.get("targetValue", "0")

            step_type_map = {
                "Warmup": (StepType.WARMUP, "warmup"),
                "Cooldown": (StepType.COOLDOWN, "cooldown"),
                "Recovery": (StepType.RECOVERY, "recovery"),
                "Rest": (StepType.REST, "rest"),
                "Interval": (StepType.INTERVAL, "interval")
            }
            step_type_id, step_type_key = step_type_map.get(step_type_str, (StepType.INTERVAL, "interval"))
            
            total_duration += duration_val

            # 타겟 설정
            target_val_one = None
            target_val_two = None
            
            if target_type_str == "speed":
                # 목표 페이스의 ±15초 범위를 생성하여 너무 타이트하지 않게 설정
                speed_slow = pace_to_ms(target_val_str, margin=15)  # 더 느린 페이스 (속도 낮음)
                speed_fast = pace_to_ms(target_val_str, margin=-15) # 더 빠른 페이스 (속도 높음)
                
                if speed_slow > 0 and speed_fast > 0:
                    target_dict = {
                        "workoutTargetTypeId": 6, # 페이스/속도 타겟 ID 6
                        "workoutTargetTypeKey": "speed",
                        "displayOrder": order
                    }
                    target_val_one = speed_slow
                    target_val_two = speed_fast
                else:
                    target_dict = {
                        "workoutTargetTypeId": TargetType.NO_TARGET,
                        "workoutTargetTypeKey": "no.target",
                        "displayOrder": order
                    }
            else:
                target_dict = {
                    "workoutTargetTypeId": TargetType.NO_TARGET,
                    "workoutTargetTypeKey": "no.target",
                    "displayOrder": order
                }

            # 종료 조건 (시간 기준)
            end_cond_model = EndConditionModel(
                conditionTypeId=ConditionType.TIME,
                conditionTypeKey="time",
                displayOrder=order
            )

            # ExecutableStep 생성 (타겟 값은 최상위 레벨에 위치해야 함)
            ex_step = ExecutableStep(
                stepOrder=order,
                stepType={
                    "stepTypeId": step_type_id,
                    "stepTypeKey": step_type_key,
                    "displayOrder": order
                },
                endCondition=end_cond_model.model_dump() if hasattr(end_cond_model, 'model_dump') else end_cond_model.dict(),
                endConditionValue=duration_val,
                targetType=target_dict,
                targetValueOne=target_val_one,
                targetValueTwo=target_val_two
            )
            executable_steps.append(ex_step)

        # 세그먼트 생성
        segment = WorkoutSegment(
            segmentOrder=1,
            sportType=SportTypeModel(sportTypeId=SportType.RUNNING, sportTypeKey="running").model_dump() if hasattr(SportTypeModel, 'model_dump') else SportTypeModel(sportTypeId=SportType.RUNNING, sportTypeKey="running").dict(),
            workoutSteps=executable_steps
        )

        # 러닝 워크아웃 객체 생성
        workout_obj = RunningWorkout(
            workoutName=name,
            description=workout_json.get('description', ''),
            workoutSegments=[segment],
            estimatedDurationInSecs=int(total_duration),
            sportType=SportTypeModel(sportTypeId=SportType.RUNNING, sportTypeKey="running").model_dump() if hasattr(SportTypeModel, 'model_dump') else SportTypeModel(sportTypeId=SportType.RUNNING, sportTypeKey="running").dict()
        )

        status = garmin.upload_running_workout(workout_obj)
        return status.get("workoutId")

    except Exception as e:
        print(f"업로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return None

def schedule_workout(garmin, workout_id, target_date):
    """특정 날짜의 캘린더에 워크아웃 예약"""
    try:
        url = f"{garmin.garmin_workouts_schedule_url}/{workout_id}"
        payload = {"date": target_date}
        garmin.garth.post("connectapi", url, json=payload, api=True)
        print(f"{target_date}로 예약됨")
    except Exception as e:
        print(f"예약 에러: {e}")

from datetime import date, datetime

def delete_gemini_workouts(garmin, future_only=True):
    """'Coach Gemini'가 포함된 기존 워크아웃 삭제"""
    print("기존 Coach Gemini 워크아웃 정리 중...")
    try:
        today = date.today().isoformat()
        workouts = garmin.get_workouts()
        deleted_count = 0
        for w in workouts:
            if "Coach Gemini" in w["workoutName"]:
                # 일단 라이브러리 중복 방지를 위해 모두 삭제
                workout_id = w["workoutId"]
                url = f"/workout-service/workout/{workout_id}"
                garmin.garth.delete("connectapi", url, api=True)
                deleted_count += 1
        print(f"{deleted_count}개의 기존 워크아웃 삭제됨")
    except Exception as e:
        print(f"정리 실패: {e}")

def run_once(garmin, include_strength=False):
    """전체 훈련 계획 생성 및 업로드 1회 실행"""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 업데이트 시작...")
    
    # 환경 변수에서 구체적인 대회 정보 가져오기 (전부 선택 사항)
    race_date = os.getenv("RACE_DATE")
    race_distance = os.getenv("RACE_DISTANCE")
    race_goal_time = os.getenv("RACE_GOAL_TIME")
    race_target_pace = os.getenv("RACE_TARGET_PACE")
    
    if race_date:
        print(f"목표 대회 설정됨: {race_date}")
        if race_distance: print(f" - 거리: {race_distance}")
        if race_goal_time: print(f" - 목표 시간: {race_goal_time}")
        if race_target_pace: print(f" - 타겟 페이스: {race_target_pace}")

    # 기존 계획 먼저 정리
    delete_gemini_workouts(garmin)

    metrics = get_advanced_metrics(garmin)
    plan_data = ask_gemini_for_plan(
        metrics, 
        include_strength=include_strength, 
        race_date=race_date, 
        race_distance=race_distance,
        race_goal_time=race_goal_time,
        race_target_pace=race_target_pace
    )

    if plan_data and "plan" in plan_data:
        print(f"\n훈련 계획 생성 완료!")
        for day in plan_data["plan"]:
            target_date = day["date"]
            workout = day["workout"]
            print(f"[{target_date}] {workout['workoutName']}")
            
            workout_id = create_garmin_workout(garmin, workout)
            if workout_id:
                schedule_workout(garmin, workout_id, target_date)
            time.sleep(1) # API 부하 방지용 딜레이
        print("업데이트 완료")
    else:
        print("계획 생성 실패")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="store_true", help="지속적인 서비스 모드로 실행")
    parser.add_argument("--hour", type=int, default=6, help="매일 실행될 시간 (0-23, 기본: 6)")
    parser.add_argument("--include-strength", action="store_true", help="계획에 근력 운동 포함 여부")
    args = parser.parse_args()

    print("--- Coach Gemini: Advanced Adaptive Trainer ---")
    garmin = login_to_garmin()
    if not garmin: return

    if args.service:
        print(f"서비스 모드 실행 중. 매일 {args.hour}:00에 예약됨. (근력운동 포함: {args.include_strength})")
        last_run_date = None
        while True:
            now = datetime.now()
            if now.hour == args.hour and last_run_date != now.date():
                try:
                    run_once(garmin, include_strength=args.include_strength)
                    last_run_date = now.date()
                except Exception as e:
                    print(f"정기 실행 중 에러 발생: {e}")
            
            # 15분마다 체크
            time.sleep(900) 
    else:
        run_once(garmin, include_strength=args.include_strength)

if __name__ == "__main__":
    main()
