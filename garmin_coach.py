import os
import json
import time
import schedule
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
from garminconnect import Garmin
from google import genai
from google.genai import types

# 구글 캘린더 API 관련
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 환경 변수 로드
load_dotenv()

# 가민 토큰 경로 설정
TOKEN_DIR = os.path.abspath(".garmin_tokens")
os.environ["GARMINTOKENS"] = TOKEN_DIR

# 구글 OAuth 스코프 변경 허용 (라이브러리 경고 방지)
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

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

    # 1. 기본 통계 및 수면 점수
    try:
        stats = garmin.get_user_summary(today)
        
        # 수면 상세 데이터 추출 함수
        def get_sleep_details(d):
            try:
                s_data = garmin.get_sleep_data(d)
                dto = s_data.get('dailySleepDTO', {})
                scores = dto.get('sleepScores', {}).get('overall', {})
                
                # 초 단위를 'H시간 M분' 형식으로 변환
                def format_seconds(s):
                    if not s: return "0분"
                    h = s // 3600
                    m = (s % 3600) // 60
                    return f"{h}시간 {m}분" if h > 0 else f"{m}분"

                return {
                    "score": scores.get('value'),
                    "quality": scores.get('qualifierKey'),
                    "duration": format_seconds(dto.get('sleepTimeSeconds')),
                    "deep": format_seconds(dto.get('deepSleepSeconds')),
                    "light": format_seconds(dto.get('lightSleepSeconds')),
                    "rem": format_seconds(dto.get('remSleepSeconds')),
                    "awake": format_seconds(dto.get('awakeSleepSeconds'))
                }
            except: return None

        sleep_details = get_sleep_details(today)
        
        # 폴백 제거: 오늘 데이터가 없으면 N/A 처리 (사용자 요청)
        if not sleep_details or not sleep_details.get('score'):
            sleep_score_display = 'N/A'
            sleep_info_for_gemini = "기록 없음 (워치 미착용 등)"
        else:
            sleep_score_display = sleep_details['score']
            sleep_info_for_gemini = (
                f"점수: {sleep_details['score']} ({sleep_details['quality']}), "
                f"총 수면: {sleep_details['duration']} (깊은: {sleep_details['deep']}, "
                f"가벼운: {sleep_details['light']}, REM: {sleep_details['rem']}, 깨어남: {sleep_details['awake']})"
            )
        
        print(f" - 기본 통계 수집 완료: 걸음 수 {stats.get('totalSteps', 0)}, 수면 점수 {sleep_score_display}")
        if sleep_score_display != 'N/A':
            print(f"   * 상세 수면: {sleep_info_for_gemini}")
            
    except Exception as e:
        print(f" - 기본 통계 수집 실패: {e}")
        stats = {}
        sleep_score_display = 'N/A'
        sleep_info_for_gemini = "데이터 수집 실패"
    
    # 2. 바디 배터리
    try:
        bb_data = garmin.get_body_battery(today)
        bb_val = "알 수 없음"
        if bb_data and isinstance(bb_data, list):
            last_entry = bb_data[-1]
            if 'bodyBatteryValuesArray' in last_entry:
                values = last_entry['bodyBatteryValuesArray']
                if values: bb_val = values[-1][1]
        print(f" - 바디 배터리 수집 완료: {bb_val}")
    except Exception as e:
        print(f" - 바디 배터리 수집 실패: {e}")
        bb_val = "알 수 없음"

    # 3. 개인 기록 (PR) 및 최대 심박수
    try:
        prs_raw = garmin.get_personal_record()
        major_prs = []
        
        PR_TYPE_MAP = {
            1: '1K', 2: 'MILE', 3: '5K', 4: '10K', 
            5: 'HALF_MARATHON', 6: 'MARATHON', 7: 'LONG_RUN'
        }
        
        all_recs = []
        if isinstance(prs_raw, dict):
            for sport_recs in prs_raw.values():
                if isinstance(sport_recs, list): all_recs.extend(sport_recs)
        elif isinstance(prs_raw, list):
            all_recs = prs_raw
            
        for group in all_recs:
            recs = group.get('prs', []) if isinstance(group, dict) and 'prs' in group else [group]
            for pr in recs:
                if not isinstance(pr, dict): continue
                t_id = pr.get('typeId')
                p_type = pr.get('typeKey') or pr.get('type') or PR_TYPE_MAP.get(t_id)
                val = (pr.get('value') or pr.get('recordValue') or pr.get('prValue') or 
                       pr.get('personalRecordValue') or pr.get('time'))
                
                if p_type:
                    norm_type = str(p_type).upper()
                    target_matches = ['1K', 'MILE', '5K', '10K', 'HALF', 'MARATHON']
                    if any(t in norm_type for t in target_matches) and val:
                        try:
                            v_float = float(val)
                            h = int(v_float // 3600)
                            m = int((v_float % 3600) // 60)
                            s = int(v_float % 60)
                            time_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
                            major_prs.append(f"{p_type}: {time_str}")
                        except: continue
        
        pr_display = ", ".join(major_prs) if major_prs else f"{len(prs_raw) if prs_raw else 0} 개의 기록"
        print(f" - 개인 기록(PR) 수집 완료: {pr_display}")
        
        # 3-2. 최대 심박수 (사용자 설정값 우선)
        max_hr = os.getenv("MAX_HEART_RATE")
        if max_hr:
            try:
                max_hr = int(max_hr)
                print(f" - 최대 심박수 설정 확인: {max_hr} bpm (환경 변수)")
            except:
                print(f" - 최대 심박수 설정 오류: '{max_hr}'은 올바른 숫자가 아님")
                max_hr = None
        else:
            # 설정값이 없으면 로그를 남기지 않거나 '미설정' 표시
            pass
        
    except Exception as e:
        print(f" - 개인 기록/최대심박수 수집 오류: {e}")
        major_prs = []
        max_hr = None

    # 4. 훈련 상태 및 부하
    try:
        status = garmin.get_training_status(today)
        
        # VO2Max 안전하게 가져오기
        vo2_max_obj = status.get('mostRecentVO2Max', {})
        if isinstance(vo2_max_obj, dict):
            vo2_max = vo2_max_obj.get('generic', {}).get('vo2MaxValue', 'N/A')
        else:
            vo2_max = 'N/A'
        
        # 훈련 상태 및 부하 피드백 추출
        train_status = 'N/A'
        load_balance_phrase = 'N/A'
        acwr_val = 'N/A'
        acute_load = 'N/A'
        
        # 1) 훈련 상태 및 ACWR 피드백 (mostRecentTrainingStatus -> latestTrainingStatusData 내부 순회)
        mrt_status = status.get('mostRecentTrainingStatus', {})
        if isinstance(mrt_status, dict):
            ltsd = mrt_status.get('latestTrainingStatusData', {})
            if isinstance(ltsd, dict):
                for device_id, data in ltsd.items():
                    if isinstance(data, dict):
                        # 상태 문구
                        phrase = data.get('trainingStatusFeedbackPhrase')
                        if phrase: train_status = phrase
                        
                        # ACWR (급성/만성 부하 비율)
                        acwr_dto = data.get('acuteTrainingLoadDTO', {})
                        if isinstance(acwr_dto, dict):
                            ratio = acwr_dto.get('dailyAcuteChronicWorkloadRatio')
                            if ratio is not None: acwr_val = ratio
                            acute_load = acwr_dto.get('dailyTrainingLoadAcute', 'N/A')
                        break
        
        # 2) 훈련 부하 밸런스 (mostRecentTrainingLoadBalance -> metricsTrainingLoadBalanceDTOMap 내부 순회)
        mrtl_balance = status.get('mostRecentTrainingLoadBalance', {})
        if isinstance(mrtl_balance, dict):
            mtlbdms = mrtl_balance.get('metricsTrainingLoadBalanceDTOMap', {})
            if isinstance(mtlbdms, dict):
                for device_id, data in mtlbdms.items():
                    if isinstance(data, dict):
                        phrase = data.get('trainingBalanceFeedbackPhrase')
                        if phrase:
                            load_balance_phrase = phrase
                            break
        
        # 상세 훈련 데이터 요약 생성 (Gemini 분석용)
        training_info_for_gemini = (
            f"상태: {train_status}, 부하 밸런스: {load_balance_phrase}, "
            f"ACWR: {acwr_val}, 급성 부하: {acute_load}"
        )
        
        print(f" - 훈련 상태 수집 완료: {train_status} (ACWR: {acwr_val}), VO2Max: {vo2_max}")
        print(f"   * 상세 부하: {training_info_for_gemini}")
    except Exception as e:
        print(f" - 훈련 상태 수집 실패: {e}")
        vo2_max = 'N/A'
        train_status = 'N/A'
        training_info_for_gemini = "데이터 수집 실패"

    # 5. 젖산 역치
    try:
        threshold = garmin.get_lactate_threshold()
        threshold_display = "기록 없음"
        threshold_for_gemini = None
        
        if threshold:
            speed_raw = threshold.get('speed_and_heart_rate', {}).get('speed')
            hr = threshold.get('speed_and_heart_rate', {}).get('heartRate')
            if speed_raw and hr:
                # 가민 API의 속도 값은 가끔 0.1배인 경우가 있음 (예: 0.355 m/s -> 3.55 m/s)
                # 달리기의 경우 1.0 m/s 이하는 비정상적으로 느리므로 10배로 보정
                speed = speed_raw * 10 if speed_raw < 1.0 else speed_raw
                seconds_per_km = 1 / speed * 1000
                m = int(seconds_per_km // 60)
                s = int(seconds_per_km % 60)
                threshold_display = f"페이스 {m}:{s:02d}/km, 심박수 {hr}bpm"
                
                # Gemini용 간소화된 객체
                threshold_for_gemini = {
                    "pace": f"{m}:{s:02d}/km",
                    "heartRate": hr
                }
            else:
                threshold_display = str(threshold)
        print(f" - 젖산 역치 정보 수집 완료: {threshold_display}")
    except Exception as e:
        print(f" - 젖산 역치 수집 실패: {e}")
        threshold_for_gemini = None

    # 6. HRV (심박 변이도)
    try:
        hrv_data = garmin.get_hrv_data(today)
        hrv_summary = hrv_data.get("hrvSummary", {})
        hrv_avg = hrv_summary.get("lastNightAvg", "알 수 없음")
        print(f" - HRV 정보 수집 완료: {hrv_avg}")
    except Exception as e:
        print(f" - HRV 수집 실패: {e}")
        hrv_avg = "알 수 없음"

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
        print(f" - 어제 활동 내역 수집 완료: {len(actual_yesterday)} 개의 활동")
    except Exception as e:
        print(f" - 어제 활동 내역 수집 실패: {e}")
        actual_yesterday = []

    # 8. 최근 30일간의 일정 및 활동 (컨텍스트 파악용)
    try:
        today_date = date.today()
        thirty_days_ago = today_date - timedelta(days=30)
        
        # 조회할 월 리스트 생성 (이번 달, 지난달)
        months_to_fetch = []
        curr = today_date
        months_to_fetch.append((curr.year, curr.month))
        
        # 지난달 계산
        first_of_curr = curr.replace(day=1)
        last_month_end = first_of_curr - timedelta(days=1)
        months_to_fetch.append((last_month_end.year, last_month_end.month))
        
        all_items = []
        for y, m in months_to_fetch:
            url = f"/calendar-service/year/{y}/month/{m-1}" # 0-indexed month
            try:
                resp = garmin.garth.get("connectapi", url, api=True)
                cal_data = resp.json()
                all_items.extend(cal_data.get("calendarItems", []))
            except: continue

        existing_plan = []
        seen_ids = set() # 중복 처리용 (달이 겹칠 수 있음)
        
        for item in all_items:
            item_id = item.get("id")
            if item_id in seen_ids: continue
            
            item_date_str = item.get("date")
            if not item_date_str: continue
            item_date = date.fromisoformat(item_date_str)
            
            # 최근 30일 이내인지 확인
            if thirty_days_ago <= item_date <= today_date:
                item_type = item.get("itemType")
                if item_type in ["workout", "activity"]:
                    summary = ""
                    if item_type == "activity":
                        raw_dist = item.get('activeSplitSummaryDistance') or item.get('distance', 0)
                        dist_km = round(float(raw_dist) / 1000, 2) if raw_dist else 0
                        
                        raw_dur = item.get('elapsedDuration') or (item.get('duration', 0) / 1000)
                        h = int(raw_dur // 3600)
                        m = int((raw_dur % 3600) // 60)
                        s = int(raw_dur % 60)
                        dur_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
                        
                        avg_hr = item.get('averageHR', 'N/A')
                        summary = f"({dist_km}km, {dur_str}, HR: {avg_hr})"

                    existing_plan.append({
                        "date": item_date_str,
                        "title": item.get("title"),
                        "type": item_type,
                        "details": summary
                    })
                    seen_ids.add(item_id)
        
        # 날짜순 정렬
        existing_plan.sort(key=lambda x: x['date'])
        print(f" - 최근 30일 훈련 및 활동 수집 완료: {len(existing_plan)} 개의 항목")
        # print("existing_plan:", existing_plan)
    except Exception as e:
        print(f" - 최근 일정 수집 실패: {e}")
        existing_plan = []

    # 9. 연간 요약 (장기 트렌드 파악용)
    try:
        # 최근 1년치 활동 리스트 가져오기 (최대 500개)
        all_activities = garmin.get_activities(0, 500)
        yearly_stats = {} # {(year, month): {"dist": 0, "count": 0}}
        
        limit_date = datetime.now() - timedelta(days=365)
        
        for act in all_activities:
            start_time_str = act.get("startTimeLocal")
            if not start_time_str: continue
            start_time = datetime.fromisoformat(start_time_str)
            
            if start_time < limit_date: break # 1년 이전 데이터면 조기 종료
            
            key = (start_time.year, start_time.month)
            if key not in yearly_stats:
                yearly_stats[key] = {"dist": 0, "count": 0}
            
            yearly_stats[key]["dist"] += (act.get("distance", 0) / 1000)
            yearly_stats[key]["count"] += 1
            
        # 보기 좋게 정렬 및 포맷팅
        sorted_keys = sorted(yearly_stats.keys(), reverse=True)
        yearly_summary_display = []
        for y, m in sorted_keys:
            s = yearly_stats[(y, m)]
            yearly_summary_display.append(f"{y}/{m:02d}: {s['dist']:.1f}km ({s['count']}회)")
        
        print(f" - 연간 훈련 요약 수집 완료: {len(yearly_summary_display)} 개월 데이터")
        # print("yearly_summary_display:", yearly_summary_display)
    except Exception as e:
        print(f" - 연간 요약 수집 실패: {e}")
        yearly_summary_display = []

    return {
        "date": today,
        "health": {
            "steps": stats.get("totalSteps"),
            "sleepScore": sleep_score_display,
            "sleepDetails": sleep_info_for_gemini,
            "restingHR": stats.get("restingHeartRate"),
            "bodyBattery": bb_val,
            "hrv": hrv_avg
        },
        "performance": {
            "personalRecords": major_prs,
            "trainingStatus": train_status,
            "trainingDetails": training_info_for_gemini,
            "vo2Max": vo2_max,
            **( {"lactateThreshold": threshold_for_gemini} if threshold_for_gemini else {} ),
            **( {"maxHeartRate": max_hr} if max_hr else {} )
        },
        "context": {
            "yesterday_actual": actual_yesterday,
            "current_schedule": existing_plan,
            "yearly_trend": yearly_summary_display
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
        return None

def get_google_calendar_service():
    """구글 캘린더 서비스 객체 생성 및 인증"""
    SCOPES = ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar"]
    creds = None
    token_path = "token_google.json"
    creds_path = "credentials.json"

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                print(f"경고: 구글 인증 파일 '{creds_path}'가 없음. 구글 캘린더 동기화를 건너뜁니다.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=False)
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("calendar", "v3", credentials=creds)
        return service
    except Exception as e:
        print(f"구글 캘린더 서비스 생성 에러: {e}")
        return None

def sync_to_google_calendar(plan_data):
    """생성된 훈련 계획을 구글 캘린더에 동기화"""
    service = get_google_calendar_service()
    if not service:
        return

    calendar_name = "Coach Gemini"
    calendar_id = None

    try:
        # 1. 전용 캘린더 찾기 또는 생성
        calendars = service.calendarList().list().execute().get('items', [])
        for cal in calendars:
            if cal.get('summary') == calendar_name:
                calendar_id = cal.get('id')
                break
        
        if not calendar_id:
            print(f"구글 캘린더 생성 중: {calendar_name}")
            new_cal = {'summary': calendar_name, 'timeZone': 'Asia/Seoul'}
            created_cal = service.calendars().insert(body=new_cal).execute()
            calendar_id = created_cal.get('id')

        # 2. 기존 일정 정리 (어제부터 10일치)
        # 중요: 하루 종일 일정(all-day events)은 시간 없이 날짜만 있으므로 
        # 범위를 UTC 자정 기준으로 넉넉히 잡아야 확실히 삭제됩니다.
        from datetime import timezone
        now_utc = datetime.now(timezone.utc)
        start_cleanup = (now_utc - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_cleanup = (now_utc + timedelta(days=10)).replace(hour=23, minute=59, second=59, microsecond=0)
        
        time_min = start_cleanup.isoformat()
        time_max = end_cleanup.isoformat()
        
        events = service.events().list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max).execute().get('items', [])
        for event in events:
            service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()

        # 3. 새로운 일정 등록
        print("구글 캘린더에 일정 등록 중...")
        for day in plan_data.get('plan', []):
            workout = day.get('workout')
            if not workout or "Rest" in workout.get('workoutName', ''):
                continue
            
            event_date = day.get('date')
            
            # 제목에서 "Coach Gemini: " 접두어 제거
            display_title = workout.get('workoutName', '').replace("Coach Gemini: ", "").strip()
            
            # 상세 설명 구축 (운동 단계 + 한국어 설명)
            desc_lines = []
            
            # 1. 운동 단계 요약 추가
            steps = workout.get('steps', [])
            if steps:
                desc_lines.append("🏃‍♂️ <b>훈련 단계:</b>")
                for i, step in enumerate(steps):
                    s_type = step.get('type', 'Run')
                    duration = step.get('durationValue', 0)
                    
                    # 초 단위 시간을 분:초로 변환
                    if duration >= 60:
                        dur_str = f"{duration // 60}분 {duration % 60}초" if duration % 60 else f"{duration // 60}분"
                    else:
                        dur_str = f"{duration}초"
                        
                    target = step.get('targetValue', '')
                    target_str = f" (목표 페이스: {target})" if target and target != "0:00" else ""
                    
                    desc_lines.append(f"{i+1}. {s_type}: {dur_str}{target_str}")
                desc_lines.append("") # 줄바꿈
            
            # 2. 기존 한국어 설명 추가
            rationale = workout.get('description', '')
            if rationale:
                formatted_rationale = rationale.replace('\n', '<br>')
                desc_lines.append(f"📝 <b>코치 리포트:</b><br>{formatted_rationale}")
            
            event = {
                'summary': display_title,
                'description': "<br>".join(desc_lines),
                'start': {'date': event_date},
                'end': {'date': event_date},
                'colorId': '1' # 라벤더 색상
            }
            service.events().insert(calendarId=calendar_id, body=event).execute()
        print("구글 캘린더 동기화 완료!")

    except Exception as e:
        print(f"구글 캘린더 동기화 중 에러 발생: {e}")

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
    - Recent Health: {json.dumps(metrics['health'], ensure_ascii=False)}
    - Performance: {json.dumps(metrics['performance'], ensure_ascii=False)} (includes PRs, VO2Max, Lactate Threshold, and optionally Max Heart Rate if provided)
    - Context (Yesterday Actual vs Planned): {json.dumps(metrics['context'], ensure_ascii=False)}

    
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
            "durationValue": 1800,
            "durationUnit": "second",
            "targetType": "no_target|speed",
            "targetValue": "MM:SS"
          }}
        ]
      }}
    }}
    
    Return ONLY valid JSON.
    """

    print("prompt:", prompt)
    
    print("Gemini로 7일 훈련 계획 생성 중...")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                # model="gemini-2.5-flash",
                # model="gemini-3-flash-preview",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            text = response.text
            
            # 1. 마크다운 블록 제거 및 순수 JSON 추출
            if "```json" in text:
                text = text.split("```json")[-1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[-1].split("```")[0].strip()
            
            # 2. 제어 문자 및 잘못된 이스케이프 정제
            import re
            # 불완전하거나 유효하지 않은 백슬래시 이스케이프 처리
            # JSON 표준에서 허용되지 않는 백슬래시들을 이중 백슬래시로 변환하거나 제거
            # 특히 한국어 설명 부분에서 발생할 수 있는 이스케이프 오염 방지
            text = text.replace('\n', ' ').replace('\r', '') 
            # 유효하지 않은 이스케이브(\ 뒤에 " \ / b f n r t u 가 아닌 것)를 찾아서 백슬래시 제거
            text = re.sub(r'\\(?![ux"\\\/bfnrt])', r'', text)
            
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError as je:
                print(f"JSON 파싱 실패 (위치: {je.pos}): {je.msg}")
                # 디버깅을 위해 에러 주변 텍스트 출력
                start = max(0, je.pos - 40)
                end = min(len(text), je.pos + 40)
                print(f"에러 주변 컨텍스트: ...{text[start:end]}...")
                raise je
        except Exception as e:
            if "429" in str(e):
                print(f"API 할당량 초과. 45초 후 재시도... ({attempt+1}/3)")
                time.sleep(45)
            else:
                print(f"Gemini API 에러: {e}")
                if attempt == 2: return None
                print(f"재시도 중... ({attempt+1}/3)")
                time.sleep(2)
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
        for day in plan_data['plan']:
            target_date = day["date"]
            workout = day["workout"]
            
            if "Rest" in workout['workoutName']:
                print(f"[{target_date}] 휴식")
                continue
            
            print(f"[{target_date}] {workout['workoutName']}")
            workout_id = create_garmin_workout(garmin, workout)
            if workout_id:
                schedule_workout(garmin, workout_id, target_date)
            time.sleep(1) # API 부하 방지용 딜레이
        
        # 구글 캘린더 동기화 추가
        sync_to_google_calendar(plan_data)
        
        print("\n업데이트 완료")
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
    
    # 시스템 시간 및 타임존 정보 출력 (KST 확인용)
    now = datetime.now()
    tz_info = time.strftime("%Z")
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_info}] 시스템 시작됨")

    garmin = login_to_garmin()
    if not garmin: return

    if args.service:
        target_time = f"{args.hour:02d}:00"
        print(f"이미 서비스 모드 실행 중. 매일 {target_time}에 예약됨. (근력운동 포함: {args.include_strength})")
        
        # 스케줄 등록
        schedule.every().day.at(target_time).do(run_once, garmin, include_strength=args.include_strength)
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 스케줄러 시작됨. 다음 실행: {schedule.next_run()}")
        
        while True:
            schedule.run_pending()
            time.sleep(60) # 1분마다 스케줄만 체크
    else:
        run_once(garmin, include_strength=args.include_strength)

if __name__ == "__main__":
    main()
