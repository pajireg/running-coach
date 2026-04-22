from datetime import date

from running_coach.clients.gemini.planner import TrainingPlanner
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics


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


def test_build_weekly_skeleton_spaces_recent_long_run_when_recovery_is_not_strong():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 19),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=17.0,
            recent_30d_run_distance_km=72.0,
            recent_30d_run_count=10,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(distance="10K", goal_time="49:00"),
        training_background={
            "coachingState": {
                "readinessScore": 58,
                "fatigueScore": 55,
                "injuryRiskScore": 25,
                "load": {"daysSinceLongRun": 1},
            },
            "planningConstraints": {
                "availability": [
                    {
                        "weekday": 5,
                        "isAvailable": True,
                        "maxDurationMinutes": 90,
                        "preferredSessionType": "long_run",
                    },
                    {
                        "weekday": 6,
                        "isAvailable": True,
                        "maxDurationMinutes": 90,
                        "preferredSessionType": "long_run",
                    },
                ],
            },
        },
    )

    today = next(day for day in skeleton if day["date"] == "2026-04-19")
    long_runs = [day for day in skeleton if day["sessionType"] == "long_run"]
    assert today["sessionType"] != "long_run"
    assert len(long_runs) == 1
    assert long_runs[0]["date"] == "2026-04-25"
    assert "회복 요구도" in long_runs[0]["descriptionGuide"]


def test_build_weekly_skeleton_allows_close_long_run_when_state_is_strong():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 19),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=17.0,
            recent_30d_run_distance_km=72.0,
            recent_30d_run_count=10,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(distance="10K", goal_time="49:00"),
        training_background={
            "coachingState": {
                "readinessScore": 76,
                "fatigueScore": 42,
                "injuryRiskScore": 18,
                "load": {"daysSinceLongRun": 1},
            },
            "planningConstraints": {
                "availability": [
                    {
                        "weekday": 5,
                        "isAvailable": True,
                        "maxDurationMinutes": 90,
                        "preferredSessionType": "long_run",
                    },
                    {
                        "weekday": 6,
                        "isAvailable": True,
                        "maxDurationMinutes": 90,
                        "preferredSessionType": "long_run",
                    },
                ],
            },
        },
    )

    today = next(day for day in skeleton if day["date"] == "2026-04-19")
    assert today["sessionType"] == "long_run"
    assert "회복·부하 신호가 안정적" in today["descriptionGuide"]


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
    assert "2026-04-20은(는) 불가 요일" in monday["descriptionGuide"]
    rest_days = [
        day for day in skeleton if day["sessionType"] == "rest" and day["date"] != "2026-04-20"
    ]
    assert all("2026-04-20은(는) 불가 요일" not in day["descriptionGuide"] for day in rest_days)


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


def test_build_weekly_skeleton_reduces_quality_when_reduced_stimulus_repeats():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=28.0,
            recent_30d_run_distance_km=92.0,
            recent_30d_run_count=11,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 62,
                "fatigueScore": 48,
                "injuryRiskScore": 20,
                "executionInsights": {
                    "reducedStimulusCount": 2,
                    "excessiveStimulusCount": 0,
                    "scheduleShiftCount": 0,
                    "unplannedSessionCount": 0,
                },
            }
        },
    )

    assert sum(1 for day in skeleton if day["sessionType"] == "quality") == 0
    assert sum(1 for day in skeleton if day["sessionType"] == "rest") >= 1


def test_build_weekly_skeleton_adds_recovery_when_excessive_stimulus_repeats():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=30.0,
            recent_30d_run_distance_km=100.0,
            recent_30d_run_count=12,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 60,
                "fatigueScore": 45,
                "injuryRiskScore": 22,
                "executionInsights": {
                    "reducedStimulusCount": 0,
                    "excessiveStimulusCount": 2,
                    "scheduleShiftCount": 0,
                    "unplannedSessionCount": 2,
                },
            }
        },
    )

    assert sum(1 for day in skeleton if day["sessionType"] == "quality") == 0
    assert sum(1 for day in skeleton if day["sessionType"] == "rest") >= 2
    assert any("강한 자극" in day["descriptionGuide"] for day in skeleton)


def test_build_weekly_skeleton_reacts_more_strongly_to_unplanned_hard_sessions():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=30.0,
            recent_30d_run_distance_km=95.0,
            recent_30d_run_count=11,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 58,
                "fatigueScore": 44,
                "injuryRiskScore": 24,
                "executionInsights": {
                    "reducedStimulusCount": 0,
                    "excessiveStimulusCount": 0,
                    "scheduleShiftCount": 0,
                    "unplannedSessionCount": 1,
                    "unplannedEasyCount": 0,
                    "unplannedHardCount": 1,
                },
            }
        },
    )

    assert sum(1 for day in skeleton if day["sessionType"] == "quality") == 0
    assert sum(1 for day in skeleton if day["sessionType"] == "rest") >= 2
    assert any("비계획 고강도" in day["descriptionGuide"] for day in skeleton)


def test_build_weekly_skeleton_reduces_quality_when_recovery_runs_are_too_hard():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=28.0,
            recent_30d_run_distance_km=88.0,
            recent_30d_run_count=10,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 63,
                "fatigueScore": 46,
                "injuryRiskScore": 22,
                "executionInsights": {
                    "recoveryTooHardCount": 1,
                    "qualityWellExecutedCount": 0,
                },
            }
        },
    )

    assert sum(1 for day in skeleton if day["sessionType"] == "quality") == 0
    assert any("easy/recovery 강도 통제" in day["descriptionGuide"] for day in skeleton)


def test_build_weekly_skeleton_keeps_structure_when_quality_is_well_executed():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=30.0,
            recent_30d_run_distance_km=96.0,
            recent_30d_run_count=11,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 68,
                "fatigueScore": 44,
                "injuryRiskScore": 24,
                "executionInsights": {
                    "qualityWellExecutedCount": 2,
                    "recoveryTooHardCount": 0,
                },
            }
        },
    )

    assert sum(1 for day in skeleton if day["sessionType"] == "quality") == 1
    assert any("품질 세션의 실제 자극이 안정적" in day["descriptionGuide"] for day in skeleton)


def test_build_weekly_skeleton_shortens_long_run_when_recent_long_run_was_too_hard():
    planner = TrainingPlanner(gemini_client=None)
    metrics = AdvancedMetrics(
        date=date(2026, 4, 17),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(
            recent_7d_run_distance_km=32.0,
            recent_30d_run_distance_km=104.0,
            recent_30d_run_count=12,
        ),
    )

    skeleton = planner._build_weekly_skeleton(
        metrics=metrics,
        race_config=RaceConfig(),
        training_background={
            "coachingState": {
                "readinessScore": 61,
                "fatigueScore": 47,
                "injuryRiskScore": 24,
                "executionInsights": {
                    "longRunTooHardCount": 1,
                },
            }
        },
    )

    long_run = next(day for day in skeleton if day["sessionType"] == "long_run")
    assert long_run["targetMinutes"] < 78
    assert "롱런 후반 강도" in long_run["descriptionGuide"]
