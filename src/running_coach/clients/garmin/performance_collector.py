"""퍼포먼스 데이터 수집기"""

from datetime import date
from typing import List, Optional

from ...config.constants import PR_TYPE_MAP
from ...models.performance import LactateThreshold, PerformanceMetrics, PersonalRecord, TrainingLoad
from ...utils.logger import get_logger
from .utils import safe_get

logger = get_logger(__name__)


class PerformanceDataCollector:
    """퍼포먼스 데이터 수집기"""

    def __init__(self, garmin_connection, settings):
        """
        Args:
            garmin_connection: garminconnect.Garmin 인스턴스
            settings: Settings 인스턴스
        """
        self.garmin = garmin_connection
        self.settings = settings

    def collect(self, target_date: date) -> PerformanceMetrics:
        """퍼포먼스 지표 수집 (통합)

        Args:
            target_date: 수집할 날짜

        Returns:
            PerformanceMetrics 모델
        """
        logger.info("퍼포먼스 데이터 수집 중...")
        date_str = target_date.isoformat()

        return PerformanceMetrics(
            personal_records=self._get_personal_records(),
            training_load=self._get_training_load(date_str),
            vo2_max=self._get_vo2_max(date_str),
            lactate_threshold=self._get_lactate_threshold(),
            max_heart_rate=self._get_max_hr(),
        )

    def _get_personal_records(self) -> List[PersonalRecord]:
        """개인 기록 수집"""
        try:
            prs_raw = self.garmin.get_personal_record()
            prs = []

            # PR 데이터 평탄화
            all_recs = []
            if isinstance(prs_raw, dict):
                for sport_recs in prs_raw.values():
                    if isinstance(sport_recs, list):
                        all_recs.extend(sport_recs)
            elif isinstance(prs_raw, list):
                all_recs = prs_raw

            # PR 파싱
            for group in all_recs:
                recs = (
                    group.get("prs", []) if isinstance(group, dict) and "prs" in group else [group]
                )
                for pr in recs:
                    if not isinstance(pr, dict):
                        continue

                    # 타입 추출
                    t_id = pr.get("typeId")
                    p_type = pr.get("typeKey") or pr.get("type")
                    if p_type is None and isinstance(t_id, int):
                        p_type = PR_TYPE_MAP.get(t_id)

                    # 값 추출
                    val = (
                        pr.get("value")
                        or pr.get("recordValue")
                        or pr.get("prValue")
                        or pr.get("personalRecordValue")
                        or pr.get("time")
                    )

                    if p_type:
                        norm_type = str(p_type).upper()
                        target_matches = ["1K", "MILE", "5K", "10K", "HALF", "MARATHON"]

                        if any(t in norm_type for t in target_matches) and val:
                            try:
                                v_float = float(val)
                                h = int(v_float // 3600)
                                m = int((v_float % 3600) // 60)
                                s = int(v_float % 60)
                                time_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"

                                prs.append(
                                    PersonalRecord(
                                        type=str(p_type),
                                        time_seconds=v_float,
                                        formatted_time=time_str,
                                    )
                                )
                            except (TypeError, ValueError):
                                continue

            pr_summary = (
                ", ".join([pr.display for pr in prs])
                if prs
                else f"{len(prs_raw) if prs_raw else 0} 개의 기록"
            )
            logger.info(f"개인 기록(PR) 수집 완료: {pr_summary}")
            return prs

        except Exception as e:
            logger.error(f"개인 기록/최대심박수 수집 오류: {e}")
            return []

    def _get_max_hr(self) -> Optional[int]:
        """최대 심박수"""
        max_hr = self.settings.max_heart_rate
        if max_hr:
            logger.info(f"최대 심박수 설정 확인: {max_hr} bpm (환경 변수)")
            return int(max_hr)
        return None

    def _get_vo2_max(self, date_str: str) -> Optional[float]:
        """VO2Max 수집"""
        try:
            status = self.garmin.get_training_status(date_str)
            vo2_max_obj = status.get("mostRecentVO2Max", {})

            if isinstance(vo2_max_obj, dict):
                vo2_val = safe_get(vo2_max_obj, "generic", "vo2MaxValue")
                if vo2_val and vo2_val != "N/A":
                    logger.debug(f"VO2Max: {vo2_val}")
                    return float(vo2_val)
            return None

        except Exception as e:
            logger.warning(f"VO2Max 수집 실패: {e}")
            return None

    def _get_training_load(self, date_str: str) -> TrainingLoad:
        """훈련 부하 수집"""
        try:
            status = self.garmin.get_training_status(date_str)

            # 초기화
            train_status = "N/A"
            load_balance_phrase = "N/A"
            acwr_val = None
            acute_load = None
            chronic_load = None

            # 1) 훈련 상태 및 ACWR 피드백
            mrt_status = status.get("mostRecentTrainingStatus", {})
            if isinstance(mrt_status, dict):
                ltsd = mrt_status.get("latestTrainingStatusData", {})
                if isinstance(ltsd, dict):
                    for device_id, data in ltsd.items():
                        if isinstance(data, dict):
                            # 상태 문구
                            phrase = data.get("trainingStatusFeedbackPhrase")
                            if phrase:
                                train_status = phrase

                            # ACWR (급성/만성 부하 비율)
                            acwr_dto = data.get("acuteTrainingLoadDTO", {})
                            if isinstance(acwr_dto, dict):
                                ratio = acwr_dto.get("dailyAcuteChronicWorkloadRatio")
                                if ratio is not None:
                                    acwr_val = float(ratio)
                                acute = acwr_dto.get("dailyTrainingLoadAcute")
                                if acute is not None:
                                    acute_load = float(acute)
                                chronic = acwr_dto.get("dailyTrainingLoadChronic")
                                if chronic is not None:
                                    chronic_load = float(chronic)
                            break

            # 2) 훈련 부하 밸런스
            mrtl_balance = status.get("mostRecentTrainingLoadBalance", {})
            if isinstance(mrtl_balance, dict):
                mtlbdms = mrtl_balance.get("metricsTrainingLoadBalanceDTOMap", {})
                if isinstance(mtlbdms, dict):
                    for device_id, data in mtlbdms.items():
                        if isinstance(data, dict):
                            phrase = data.get("trainingBalanceFeedbackPhrase")
                            if phrase:
                                load_balance_phrase = phrase
                                break

            training_load = TrainingLoad(
                status=train_status,
                balance_phrase=load_balance_phrase,
                acwr=acwr_val,
                acute_load=acute_load,
                chronic_load=chronic_load,
            )

            logger.info(f"훈련 상태: {train_status} (ACWR: {acwr_val})")
            logger.debug(f"상세 부하: {training_load.formatted_info}")

            return training_load

        except Exception as e:
            logger.error(f"훈련 상태 수집 실패: {e}")
            return TrainingLoad()

    def _get_lactate_threshold(self) -> Optional[LactateThreshold]:
        """젖산 역치 수집"""
        try:
            threshold = self.garmin.get_lactate_threshold()

            if not threshold:
                return None

            speed_raw = safe_get(threshold, "speed_and_heart_rate", "speed")
            hr = safe_get(threshold, "speed_and_heart_rate", "heartRate")

            if speed_raw and hr:
                # 가민 API의 속도 값은 가끔 0.1배인 경우가 있음
                # 달리기의 경우 1.0 m/s 이하는 비정상적으로 느리므로 10배로 보정
                speed = speed_raw * 10 if speed_raw < 1.0 else speed_raw
                seconds_per_km = 1 / speed * 1000
                m = int(seconds_per_km // 60)
                s = int(seconds_per_km % 60)
                pace_str = f"{m}:{s:02d}/km"

                lt = LactateThreshold(pace=pace_str, heart_rate=int(hr))

                logger.info(f"젖산 역치: 페이스 {pace_str}, 심박수 {hr}bpm")
                return lt

            return None

        except Exception as e:
            logger.warning(f"젖산 역치 수집 실패: {e}")
            return None
