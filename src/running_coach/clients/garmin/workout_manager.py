"""워크아웃 관리"""

from datetime import date
from typing import Any, Optional, cast

from garminconnect.workout import (  # type: ignore[import-untyped]
    ConditionType,
    ExecutableStep,
    RunningWorkout,
    SportType,
    StepType,
    TargetType,
    WorkoutSegment,
    create_cooldown_step,
    create_interval_step,
    create_recovery_step,
    create_warmup_step,
)

from ...config.constants import (
    DEFAULT_PACE_MARGIN,
    STEP_TYPE_MAP,
    SUPPORTED_WORKOUT_PREFIXES,
    WORKOUT_PREFIX,
)
from ...exceptions import GarminWorkoutError
from ...models.training import Workout
from ...utils.logger import get_logger
from ...utils.time_utils import pace_to_ms

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
            payload = self._build_workout_payload(workout)

            if hasattr(self.garmin, "upload_workout"):
                status = self.garmin.upload_workout(payload)
            else:
                status = self.garmin.garth.post(
                    "connectapi",
                    "/workout-service/workout",
                    json=payload,
                    api=True,
                )
            workout_id = status.get("workoutId")

            logger.info(f"워크아웃 생성 완료: ID={workout_id}")
            return str(workout_id) if workout_id is not None else None

        except Exception as e:
            logger.error(f"워크아웃 업로드 실패: {e}", exc_info=True)
            raise GarminWorkoutError(f"Failed to create workout: {e}") from e

    def schedule_workout(self, workout_id: str, target_date: date) -> dict[str, Any]:
        """특정 날짜의 캘린더에 워크아웃 예약 (라인 806-814)

        Args:
            workout_id: 워크아웃 ID
            target_date: 예약할 날짜
        """
        try:
            date_str = target_date.isoformat()
            if hasattr(self.garmin, "schedule_workout"):
                result = self.garmin.schedule_workout(workout_id, date_str)
            else:
                url = f"/workout-service/schedule/{workout_id}"
                payload = {"date": date_str}
                result = self.garmin.garth.post("connectapi", url, json=payload, api=True)
            logger.info(f"워크아웃 예약 완료: {date_str}")
            return cast(dict[str, Any], result)

        except Exception as e:
            logger.error(f"워크아웃 예약 에러: {e}")
            raise GarminWorkoutError(f"Failed to schedule workout: {e}") from e

    def delete_generated_workouts(self, future_only: bool = True) -> int:
        """현재 앱이 생성한 기존 워크아웃 삭제.

        Args:
            future_only: 미래 워크아웃만 삭제 (현재 미사용)

        Returns:
            삭제된 워크아웃 개수
        """
        logger.info("기존 %s 워크아웃 정리 중...", WORKOUT_PREFIX)

        try:
            workouts = self.garmin.get_workouts() if hasattr(self.garmin, "get_workouts") else []
            deleted_count = 0

            for w in workouts:
                workout_name = str(w.get("workoutName") or "")
                if any(prefix in workout_name for prefix in SUPPORTED_WORKOUT_PREFIXES):
                    workout_id = w["workoutId"]
                    if hasattr(self.garmin, "delete_workout"):
                        self.garmin.delete_workout(workout_id)
                    else:
                        url = f"/workout-service/workout/{workout_id}"
                        self.garmin.garth.delete("connectapi", url, api=True)
                    deleted_count += 1

            logger.info(f"{deleted_count}개의 기존 워크아웃 삭제됨")
            return deleted_count

        except Exception as e:
            logger.warning(f"워크아웃 정리 실패: {e}")
            return 0

    def _build_workout_payload(self, workout: Workout) -> dict[str, Any]:
        """Garmin typed workout 모델과 동일한 JSON 생성."""
        sport_type = {
            "sportTypeId": SportType.RUNNING,
            "sportTypeKey": "running",
            "displayOrder": 1,
        }
        executable_steps = []
        total_duration = 0

        for order, step in enumerate(workout.steps, start=1):
            duration_val = float(step.duration_value)
            step_type_key = STEP_TYPE_MAP.get(step.type, "run")
            total_duration += int(duration_val)

            target_dict, target_val_one, target_val_two = self._target_payload(step)
            executable_steps.append(
                self._build_step(
                    order=order,
                    duration_val=duration_val,
                    step_type_key=step_type_key,
                    target_dict=target_dict,
                    target_val_one=target_val_one,
                    target_val_two=target_val_two,
                )
            )

        workout_payload = RunningWorkout(
            workoutName=workout.workout_name,
            description=workout.description,
            estimatedDurationInSecs=total_duration,
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType=sport_type,
                    workoutSteps=executable_steps,
                )
            ],
        )
        return cast(dict[str, Any], workout_payload.to_dict())

    def _target_payload(self, step: Any) -> tuple[dict[str, Any], Optional[float], Optional[float]]:
        target_dict = {
            "workoutTargetTypeId": TargetType.NO_TARGET,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": TargetType.NO_TARGET,
        }
        if step.target_type != "speed":
            return target_dict, None, None

        try:
            pace_fast = pace_to_ms(step.target_value or "0:00", margin=-DEFAULT_PACE_MARGIN)
            pace_slow = pace_to_ms(step.target_value or "0:00", margin=DEFAULT_PACE_MARGIN)
        except ValueError:
            logger.warning("잘못된 페이스 형식으로 no_target 처리: %s", step.target_value)
            return target_dict, None, None

        return (
            {
                "workoutTargetTypeId": 6,
                "workoutTargetTypeKey": "pace.zone",
                "displayOrder": 6,
            },
            pace_fast,
            pace_slow,
        )

    @staticmethod
    def _build_step(
        order: int,
        duration_val: float,
        step_type_key: str,
        target_dict: dict[str, Any],
        target_val_one: Optional[float],
        target_val_two: Optional[float],
    ) -> ExecutableStep:
        if step_type_key == "warmup":
            step_payload = create_warmup_step(
                duration_val,
                step_order=order,
                target_type=target_dict,
            )
        elif step_type_key == "cooldown":
            step_payload = create_cooldown_step(
                duration_val, step_order=order, target_type=target_dict
            )
        elif step_type_key == "recovery":
            step_payload = create_recovery_step(
                duration_val, step_order=order, target_type=target_dict
            )
        else:
            step_payload = create_interval_step(
                duration_val, step_order=order, target_type=target_dict
            )
            if step_type_key == "rest":
                step_payload.stepType = {
                    "stepTypeId": StepType.REST,
                    "stepTypeKey": "rest",
                    "displayOrder": StepType.REST,
                }
                step_payload.endCondition = {
                    "conditionTypeId": ConditionType.TIME,
                    "conditionTypeKey": "time",
                    "displayOrder": ConditionType.TIME,
                    "displayable": True,
                }

        if target_val_one is not None:
            step_payload.targetValueOne = target_val_one
        if target_val_two is not None:
            step_payload.targetValueTwo = target_val_two
        return step_payload
