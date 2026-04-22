CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS athletes (
    athlete_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_key TEXT NOT NULL UNIQUE,
    garmin_email TEXT,
    display_name TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
    preferred_long_run_day TEXT,
    max_heart_rate INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_preferences (
    athlete_id UUID PRIMARY KEY REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    planner_mode TEXT CHECK (planner_mode IN ('legacy', 'llm_driven')),
    llm_provider TEXT CHECK (llm_provider IN ('gemini', 'openai', 'anthropic')),
    llm_model TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS race_goals (
    race_goal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    goal_name TEXT NOT NULL DEFAULT 'Primary Goal',
    race_date DATE,
    distance TEXT,
    goal_time TEXT,
    target_pace TEXT,
    priority SMALLINT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS training_blocks (
    training_block_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    starts_on DATE NOT NULL,
    ends_on DATE NOT NULL,
    focus TEXT,
    weekly_volume_target_km NUMERIC(6, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS availability_rules (
    availability_rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    max_duration_minutes INTEGER,
    preferred_session_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (athlete_id, weekday)
);

CREATE TABLE IF NOT EXISTS injury_status (
    injury_status_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    status_date DATE NOT NULL,
    injury_area TEXT NOT NULL,
    severity SMALLINT NOT NULL CHECK (severity BETWEEN 0 AND 10),
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subjective_feedback (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    feedback_date DATE NOT NULL,
    fatigue_score SMALLINT CHECK (fatigue_score BETWEEN 1 AND 10),
    soreness_score SMALLINT CHECK (soreness_score BETWEEN 1 AND 10),
    stress_score SMALLINT CHECK (stress_score BETWEEN 1 AND 10),
    motivation_score SMALLINT CHECK (motivation_score BETWEEN 1 AND 10),
    sleep_quality_score SMALLINT CHECK (sleep_quality_score BETWEEN 1 AND 10),
    pain_notes TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (athlete_id, feedback_date)
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    daily_metrics_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    metric_date DATE NOT NULL,
    steps INTEGER,
    sleep_score INTEGER,
    resting_hr INTEGER,
    body_battery INTEGER,
    hrv INTEGER,
    vo2_max NUMERIC(5, 2),
    lactate_threshold_pace TEXT,
    lactate_threshold_heart_rate INTEGER,
    training_status TEXT,
    load_balance_phrase TEXT,
    acute_load NUMERIC(8, 2),
    chronic_load NUMERIC(8, 2),
    acwr NUMERIC(6, 2),
    recent_7d_run_distance_km NUMERIC(8, 2) NOT NULL DEFAULT 0,
    recent_30d_run_distance_km NUMERIC(8, 2) NOT NULL DEFAULT 0,
    recent_30d_run_count INTEGER NOT NULL DEFAULT 0,
    health_payload JSONB NOT NULL,
    performance_payload JSONB NOT NULL,
    context_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (athlete_id, metric_date)
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    garmin_activity_id BIGINT,
    activity_date DATE NOT NULL,
    started_at TIMESTAMPTZ,
    name TEXT,
    sport_type TEXT,
    distance_km NUMERIC(8, 2),
    duration_seconds INTEGER,
    avg_pace TEXT,
    avg_hr INTEGER,
    max_hr INTEGER,
    elevation_gain_m NUMERIC(8, 2),
    calories INTEGER,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (athlete_id, garmin_activity_id)
);

CREATE TABLE IF NOT EXISTS activity_laps (
    activity_lap_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL REFERENCES activities(activity_id) ON DELETE CASCADE,
    lap_index INTEGER NOT NULL,
    distance_km NUMERIC(8, 2),
    duration_seconds INTEGER,
    avg_pace TEXT,
    avg_hr INTEGER,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (activity_id, lap_index)
);

CREATE TABLE IF NOT EXISTS planned_workouts (
    planned_workout_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    workout_date DATE NOT NULL,
    source TEXT NOT NULL DEFAULT 'running_coach',
    workout_name TEXT NOT NULL,
    description TEXT,
    sport_type TEXT NOT NULL,
    is_rest BOOLEAN NOT NULL DEFAULT FALSE,
    total_duration_seconds INTEGER NOT NULL DEFAULT 0,
    plan_payload JSONB NOT NULL,
    garmin_workout_id TEXT,
    garmin_schedule_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (athlete_id, workout_date, source)
);

CREATE TABLE IF NOT EXISTS workout_executions (
    workout_execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    planned_workout_id UUID REFERENCES planned_workouts(planned_workout_id) ON DELETE SET NULL,
    activity_id UUID REFERENCES activities(activity_id) ON DELETE SET NULL,
    execution_date DATE NOT NULL,
    completion_ratio NUMERIC(5, 2),
    target_match_score NUMERIC(5, 2),
    rpe SMALLINT CHECK (rpe BETWEEN 1 AND 10),
    notes TEXT,
    execution_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coach_decisions (
    coach_decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    decision_date DATE NOT NULL,
    decision_type TEXT NOT NULL,
    readiness_score NUMERIC(5, 2),
    fatigue_score NUMERIC(5, 2),
    injury_risk_score NUMERIC(5, 2),
    decision_summary TEXT NOT NULL,
    rationale JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_interactions (
    llm_interaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(athlete_id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_payload JSONB NOT NULL,
    response_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_metrics_athlete_date
    ON daily_metrics (athlete_id, metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_activities_athlete_date
    ON activities (athlete_id, activity_date DESC);

CREATE INDEX IF NOT EXISTS idx_planned_workouts_athlete_date
    ON planned_workouts (athlete_id, workout_date DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_athlete_date
    ON subjective_feedback (athlete_id, feedback_date DESC);
