"""워크아웃 관리"""

from datetime import date
from typing import Any, Optional, cast

from ...config.constants import (
    DEFAULT_PACE_MARGIN,
    STEP_TYPE_MAP,
)
from ...exceptions import GarminWorkoutError
from ...models.training import Workout
from ...utils.logger import get_logger
from ...utils.time_utils import pace_to_ms

logger = get_logger(__name__)

SPORT_TYPE_RUNNING = 1
STEP_TYPE_WARMUP = 1
STEP_TYPE_COOLDOWN = 2
STEP_TYPE_INTERVAL = 3
STEP_TYPE_RECOVERY = 4
STEP_TYPE_REST = 5
CONDITION_TYPE_TIME = 2
TARGET_TYPE_NO_TARGET = 1


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

    def delete_generated_workouts(
        self,
        workout_ids: Optional[list[str]] = None,
        future_only: bool = True,
    ) -> int:
        """현재 앱이 생성한 기존 워크아웃 삭제.

        DB에 저장된 garmin_workout_id 기준으로만 삭제한다.
        ID 없이 이름 prefix로 탐색하는 fallback은 StandardizeWorkoutName 적용 이후
        canonical 이름('Recovery Run' 등)과 prefix가 일치하지 않아 항상 0건이며,
        사용자의 동명 워크아웃을 잘못 삭제할 위험이 있으므로 제거했다.
        """
        ids_to_delete = [str(wid) for wid in (workout_ids or []) if wid]
        if not ids_to_delete:
            logger.info("삭제할 이전 워크아웃 ID 없음 (건너뜀)")
            return 0

        deleted_count = 0
        for workout_id in ids_to_delete:
            try:
                self._delete_workout(workout_id)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"워크아웃 삭제 실패 (id={workout_id}): {e}")

        logger.info(f"{deleted_count}/{len(ids_to_delete)}개의 기존 워크아웃 삭제됨")
        return deleted_count

    def _delete_workout(self, workout_id: str | int) -> None:
        if hasattr(self.garmin, "delete_workout"):
            self.garmin.delete_workout(workout_id)
            return
        url = f"/workout-service/workout/{workout_id}"
        self.garmin.garth.delete("connectapi", url, api=True)

    def _build_workout_payload(self, workout: Workout) -> dict[str, Any]:
        """Garmin workout upload JSON 생성.

        garminconnect.workout 의 typed Pydantic 모델은 0.3.x 기준 Pydantic v1
        Config 문법을 사용해 deprecation warning 을 발생시킨다. 업로드 API는
        dict payload 를 받으므로 동일한 JSON 구조를 직접 구성한다.
        """
        sport_type = {
            "sportTypeId": SPORT_TYPE_RUNNING,
            "sportTypeKey": "running",
            "displayOrder": 1,
        }
        executable_steps = []
        total_duration = 0

        for order, step in enumerate(workout.steps, start=1):
            duration_val = float(step.duration_value)
            step_type_key = STEP_TYPE_MAP.get(step.type, "run")
            total_duration += int(duration_val)

            target_dict, target_val_one, target_val_two = self._target_payload(step, workout)
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

        return {
            "workoutName": workout.workout_name,
            "sportType": sport_type,
            "estimatedDurationInSecs": total_duration,
            "workoutSegments": [
                {
                    "segmentOrder": 1,
                    "sportType": sport_type,
                    "workoutSteps": executable_steps,
                }
            ],
            "author": {},
            "description": workout.description,
        }

    def _target_payload(
        self,
        step: Any,
        workout: Workout,
    ) -> tuple[dict[str, Any], Optional[float], Optional[float]]:
        target_dict = {
            "workoutTargetTypeId": TARGET_TYPE_NO_TARGET,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": TARGET_TYPE_NO_TARGET,
        }
        if step.target_type != "speed":
            return target_dict, None, None

        try:
            margin = self._pace_margin_for_step(step, workout)
            pace_fast = pace_to_ms(step.target_value or "0:00", margin=-margin)
            pace_slow = pace_to_ms(step.target_value or "0:00", margin=margin)
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
    def _pace_margin_for_step(step: Any, workout: Workout) -> int:
        if step.type == "Warmup":
            return 45
        if step.type == "Cooldown":
            return 60
        if step.type == "Recovery":
            return 60
        workout_name = workout.workout_name.lower()
        if step.type == "Interval":
            return 15
        if "tempo" in workout_name or "threshold" in workout_name:
            return 20
        if "recovery" in workout_name:
            return 45
        if "long" in workout_name:
            return 40
        if "base" in workout_name:
            return 30
        return DEFAULT_PACE_MARGIN

    @staticmethod
    def _build_step(
        order: int,
        duration_val: float,
        step_type_key: str,
        target_dict: dict[str, Any],
        target_val_one: Optional[float],
        target_val_two: Optional[float],
    ) -> dict[str, Any]:
        if step_type_key == "warmup":
            step_type = {
                "stepTypeId": STEP_TYPE_WARMUP,
                "stepTypeKey": "warmup",
                "displayOrder": 1,
            }
        elif step_type_key == "cooldown":
            step_type = {
                "stepTypeId": STEP_TYPE_COOLDOWN,
                "stepTypeKey": "cooldown",
                "displayOrder": 2,
            }
        elif step_type_key == "recovery":
            step_type = {
                "stepTypeId": STEP_TYPE_RECOVERY,
                "stepTypeKey": "recovery",
                "displayOrder": 4,
            }
        elif step_type_key == "rest":
            step_type = {
                "stepTypeId": STEP_TYPE_REST,
                "stepTypeKey": "rest",
                "displayOrder": STEP_TYPE_REST,
            }
        else:
            step_type = {
                "stepTypeId": STEP_TYPE_INTERVAL,
                "stepTypeKey": "interval",
                "displayOrder": 3,
            }

        step_payload: dict[str, Any] = {
            "type": "ExecutableStepDTO",
            "stepOrder": order,
            "stepType": step_type,
            "endCondition": {
                "conditionTypeId": CONDITION_TYPE_TIME,
                "conditionTypeKey": "time",
                "displayOrder": CONDITION_TYPE_TIME,
                "displayable": True,
            },
            "endConditionValue": duration_val,
            "targetType": target_dict,
        }
        if target_val_one is not None:
            step_payload["targetValueOne"] = target_val_one
        if target_val_two is not None:
            step_payload["targetValueTwo"] = target_val_two
        return step_payload
