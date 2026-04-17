from datetime import date

from running_coach.clients.gemini.planner import TrainingPlanner
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics


def test_normalize_plan_json_rewrites_dates_and_invalid_targets():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )

    normalized = planner._normalize_plan_json(
        {
            "plan": [
                {
                    "date": "2099-01-01",
                    "workout": {
                        "workoutName": "Running Coach: Quality",
                        "description": "설명",
                        "sportType": "RUNNING",
                        "steps": [
                            {
                                "type": "Interval",
                                "durationValue": 2400,
                                "durationUnit": "second",
                                "targetType": "speed",
                                "targetValue": "4:30-4:40",
                            }
                        ],
                    },
                }
            ]
        },
        metrics,
        [
            {
                "date": "2026-04-17",
                "sessionType": "base",
                "targetMinutes": 40,
                "workoutName": "Running Coach: Base Run",
                "descriptionGuide": "기본 러닝",
            }
        ],
    )

    assert normalized["plan"][0]["date"] == "2026-04-17"
    step = normalized["plan"][0]["workout"]["steps"][0]
    assert step["durationValue"] == 2400
    assert step["targetType"] == "no_target"
    assert step["targetValue"] == "0:00"


def test_build_weekly_skeleton_places_long_run_on_weekend_and_limits_quality():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=26.0,
            recent_30d_run_distance_km=72.0,
            recent_30d_run_count=9,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 45,
                "fatigueScore": 70,
                "injuryRiskScore": 30,
            }
        },
    )

    long_runs = [day for day in skeleton if day["sessionType"] == "long_run"]
    quality_runs = [day for day in skeleton if day["sessionType"] == "quality"]
    assert len(long_runs) == 1
    assert date.fromisoformat(long_runs[0]["date"]).weekday() in {5, 6}
    assert len(quality_runs) <= 1


def test_normalize_plan_json_preserves_skeleton_and_uses_fallback_steps():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )
    skeleton = [
        {
            "date": "2026-04-17",
            "sessionType": "quality",
            "targetMinutes": 50,
            "workoutName": "Running Coach: Intervals",
            "descriptionGuide": "핵심 세션",
        }
    ]

    normalized = planner._normalize_plan_json(
        {
            "plan": [
                {
                    "date": "2099-01-01",
                    "workout": {
                        "workoutName": "Wrong Name",
                        "description": "설명",
                        "steps": [],
                    },
                }
            ]
        },
        metrics,
        skeleton,
    )

    day = normalized["plan"][0]
    assert day["date"] == "2026-04-17"
    assert day["workout"]["workoutName"] == "Running Coach: Intervals"
    assert day["workout"]["steps"][0]["type"] == "Warmup"
    assert any(step["type"] == "Interval" for step in day["workout"]["steps"])


def test_build_weekly_skeleton_respects_availability_and_training_block():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=20.0,
            recent_30d_run_distance_km=60.0,
            recent_30d_run_count=8,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(distance="10K", goal_time="49:00"),
        training_background={
            "coachingState": {
                "readinessScore": 55,
                "fatigueScore": 52,
                "injuryRiskScore": 20,
            },
            "planningConstraints": {
                "availability": [
                    {"weekday": 0, "isAvailable": False, "maxDurationMinutes": None},
                    {
                        "weekday": 2,
                        "isAvailable": True,
                        "maxDurationMinutes": 45,
                        "preferredSessionType": "quality",
                    },
                    {
                        "weekday": 6,
                        "isAvailable": True,
                        "maxDurationMinutes": 90,
                        "preferredSessionType": "long_run",
                    },
                ],
                "trainingBlock": {
                    "phase": "build",
                    "weeklyVolumeTargetKm": 40.0,
                },
            },
        },
    )

    monday = next(day for day in skeleton if day["date"] == "2026-04-20")
    wednesday = next(day for day in skeleton if day["date"] == "2026-04-22")
    sunday = next(day for day in skeleton if day["date"] == "2026-04-19")
    assert monday["sessionType"] == "rest"
    assert wednesday["sessionType"] == "quality"
    assert wednesday["targetMinutes"] <= 45
    assert sunday["sessionType"] == "long_run"
    assert sunday["targetMinutes"] <= 90
    assert "long run 선호 요일" in sunday["descriptionGuide"]


def test_build_weekly_skeleton_drops_quality_when_active_injury_exists():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=28.0,
            recent_30d_run_distance_km=100.0,
            recent_30d_run_count=12,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(distance="10K", goal_time="49:00"),
        training_background={
            "coachingState": {
                "readinessScore": 55,
                "fatigueScore": 45,
                "injuryRiskScore": 25,
                "activeInjury": {"severity": 4, "injuryArea": "left calf"},
            }
        },
    )

    assert all(day["sessionType"] != "quality" for day in skeleton)
    assert any(
        "회복" in day["descriptionGuide"]
        for day in skeleton
        if day["sessionType"] in {"rest", "recovery"}
    )


def test_build_weekly_skeleton_accounts_for_cross_training_load():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=25.0,
            recent_30d_run_distance_km=90.0,
            recent_30d_run_count=10,
            recent_7d_non_running_duration_minutes=260,
            recent_7d_non_running_sessions=3,
            recent_7d_non_running_types=["cycling", "hiking"],
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(distance="10K", goal_time="49:00"),
        training_background={
            "coachingState": {
                "readinessScore": 60,
                "fatigueScore": 40,
                "injuryRiskScore": 20,
            }
        },
    )

    assert sum(1 for day in skeleton if day["sessionType"] == "quality") == 0
    assert any(
        "비러닝 부하" in day["descriptionGuide"] or "자전거" in day["descriptionGuide"]
        for day in skeleton
    )
