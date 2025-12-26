"""워크아웃 관리"""
from typing import Optional
from datetime import date as DateType
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
from ...models.training import Workout
from ...utils.logger import get_logger
from ...utils.time_utils import pace_to_ms
from ...config.constants import DEFAULT_PACE_MARGIN, STEP_TYPE_MAP
from ...exceptions import GarminWorkoutError

logger = get_logger(__name__)


class WorkoutManager:
    """워크아웃 관리"""

    def __init__(self, garmin_connection):
        """
        Args:
            garmin_connection: garminconnect.Garmin 인스턴스
        """
        self.garmin = garmin_connection

    def create_workout(self, workout: Workout) -> Optional[str]:
        """가민 커넥트에 워크아웃 업로드 (라인 698-804)

        Args:
            workout: Workout 모델

        Returns:
            워크아웃 ID 또는 None
        """
        logger.info(f"워크아웃 생성 중: {workout.workout_name}")

        try:
            executable_steps = []
            total_duration = 0

            for i, step in enumerate(workout.steps):
                order = i + 1
                duration_val = float(step.duration_value)
                step_type_str = step.type
                target_type_str = step.target_type
                target_val_str = step.target_value

                # StepType 매핑
                step_type_key = STEP_TYPE_MAP.get(step_type_str, "run")
                step_type_id_map = {
                    "warmup": StepType.WARMUP,
                    "cooldown": StepType.COOLDOWN,
                    "recovery": StepType.RECOVERY,
                    "rest": StepType.REST,
                    "interval": StepType.INTERVAL,
                    "run": StepType.INTERVAL  # 기본값
                }
                step_type_id = step_type_id_map.get(step_type_key, StepType.INTERVAL)

                total_duration += duration_val

                # 타겟 설정
                target_val_one = None
                target_val_two = None

                if target_type_str == "speed":
                    # 목표 페이스의 ±15초 범위 생성
                    speed_slow = pace_to_ms(target_val_str, margin=DEFAULT_PACE_MARGIN)
                    speed_fast = pace_to_ms(target_val_str, margin=-DEFAULT_PACE_MARGIN)

                    if speed_slow > 0 and speed_fast > 0:
                        target_dict = {
                            "workoutTargetTypeId": 6,  # 페이스/속도 타겟 ID
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

                # ExecutableStep 생성
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
            sport_type_model = SportTypeModel(sportTypeId=SportType.RUNNING, sportTypeKey="running")
            segment = WorkoutSegment(
                segmentOrder=1,
                sportType=sport_type_model.model_dump() if hasattr(sport_type_model, 'model_dump') else sport_type_model.dict(),
                workoutSteps=executable_steps
            )

            # 러닝 워크아웃 객체 생성
            workout_obj = RunningWorkout(
                workoutName=workout.workout_name,
                description=workout.description,
                workoutSegments=[segment],
                estimatedDurationInSecs=int(total_duration),
                sportType=sport_type_model.model_dump() if hasattr(sport_type_model, 'model_dump') else sport_type_model.dict()
            )

            # 업로드
            status = self.garmin.upload_running_workout(workout_obj)
            workout_id = status.get("workoutId")

            logger.info(f"워크아웃 생성 완료: ID={workout_id}")
            return workout_id

        except Exception as e:
            logger.error(f"워크아웃 업로드 실패: {e}", exc_info=True)
            raise GarminWorkoutError(f"Failed to create workout: {e}") from e

    def schedule_workout(self, workout_id: str, target_date: DateType) -> None:
        """특정 날짜의 캘린더에 워크아웃 예약 (라인 806-814)

        Args:
            workout_id: 워크아웃 ID
            target_date: 예약할 날짜
        """
        try:
            date_str = target_date.isoformat()
            url = f"{self.garmin.garmin_workouts_schedule_url}/{workout_id}"
            payload = {"date": date_str}
            self.garmin.garth.post("connectapi", url, json=payload, api=True)
            logger.info(f"워크아웃 예약 완료: {date_str}")

        except Exception as e:
            logger.error(f"워크아웃 예약 에러: {e}")
            raise GarminWorkoutError(f"Failed to schedule workout: {e}") from e

    def delete_gemini_workouts(self, future_only: bool = True) -> int:
        """'Coach Gemini'가 포함된 기존 워크아웃 삭제 (라인 816-832)

        Args:
            future_only: 미래 워크아웃만 삭제 (현재 미사용)

        Returns:
            삭제된 워크아웃 개수
        """
        logger.info("기존 Coach Gemini 워크아웃 정리 중...")

        try:
            workouts = self.garmin.get_workouts()
            deleted_count = 0

            for w in workouts:
                if "Coach Gemini" in w.get("workoutName", ""):
                    workout_id = w["workoutId"]
                    url = f"/workout-service/workout/{workout_id}"
                    self.garmin.garth.delete("connectapi", url, api=True)
                    deleted_count += 1

            logger.info(f"{deleted_count}개의 기존 워크아웃 삭제됨")
            return deleted_count

        except Exception as e:
            logger.warning(f"워크아웃 정리 실패: {e}")
            return 0
