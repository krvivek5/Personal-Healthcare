from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.health.query_understanding import parse_natural_language_query
from app.schemas.inquiry import RoutingMode, TemporalScope


@patch("app.health.query_understanding.datetime")
def test_scenario_1_reference_date_determinism(mock_datetime):
    # Mock datetime.now(timezone.utc) to return 2025-06-01
    mock_now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    mock_datetime.now.return_value = mock_now

    target = parse_natural_language_query("What was my blood work last year?")
    assert target.temporal_scope == TemporalScope.INTERVAL
    assert target.temporal_constraint is not None
    assert target.temporal_constraint.start_date == date(2024, 1, 1)
    assert target.temporal_constraint.end_date == date(2024, 12, 31)
    assert target.temporal_constraint.anchor_year == 2024


@patch("app.health.query_understanding.datetime")
def test_scenario_2_fixed_180_day_recency(mock_datetime):
    # Mock datetime.now(timezone.utc) to return 2025-06-01
    mock_now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    mock_datetime.now.return_value = mock_now

    target = parse_natural_language_query("my labs from the past 6 months")
    assert target.temporal_scope == TemporalScope.INTERVAL
    assert target.temporal_constraint is not None

    # 6 months = 180 days
    expected_start = (mock_now - timedelta(days=180)).date()
    assert target.temporal_constraint.start_date == expected_start
    assert target.temporal_constraint.end_date == date(2025, 6, 1)


@patch("app.health.query_understanding.datetime")
def test_scenario_3_explicit_calendar_year(mock_datetime):
    target = parse_natural_language_query("cholesterol in 2024")
    assert target.temporal_scope == TemporalScope.INTERVAL
    assert target.temporal_constraint is not None
    assert target.temporal_constraint.start_date == date(2024, 1, 1)
    assert target.temporal_constraint.end_date == date(2024, 12, 31)
    assert target.temporal_constraint.anchor_year == 2024


@patch("app.health.query_understanding.datetime")
def test_scenario_4_explicit_month_year(mock_datetime):
    target = parse_natural_language_query("labs in March 2024")
    assert target.temporal_scope == TemporalScope.INTERVAL
    assert target.temporal_constraint is not None
    assert target.temporal_constraint.start_date == date(2024, 3, 1)
    assert target.temporal_constraint.end_date == date(2024, 3, 31)
    assert target.temporal_constraint.anchor_year == 2024


@patch("app.health.query_understanding.datetime")
def test_scenario_5_explicit_iso_date(mock_datetime):
    target = parse_natural_language_query("cholesterol on 2024-06-15")
    assert target.temporal_scope == TemporalScope.INTERVAL
    assert target.temporal_constraint is not None
    assert target.temporal_constraint.start_date == date(2024, 6, 15)
    assert target.temporal_constraint.end_date == date(2024, 6, 15)
    assert target.temporal_constraint.anchor_year == 2024


@patch("app.health.query_understanding.datetime")
def test_scenario_6_impossible_calendar_date(mock_datetime):
    target = parse_natural_language_query("labs on February 30, 2024")
    # Invalid dates should short-circuit to UNROUTABLE
    assert target.routing_mode == RoutingMode.UNROUTABLE


@patch("app.health.query_understanding.datetime")
def test_scenario_7_inverted_range(mock_datetime):
    target = parse_natural_language_query("labs between 2024 and 2022")
    # Inverted ranges should short-circuit to UNROUTABLE
    assert target.routing_mode == RoutingMode.UNROUTABLE


@patch("app.health.query_understanding.datetime")
def test_scenario_14_deterministic_superlative_fallback(mock_datetime):
    target = parse_natural_language_query("latest cholesterol")
    assert target.temporal_scope == TemporalScope.ALL
    assert target.temporal_constraint is not None
    assert target.temporal_constraint.start_date is None
    assert target.temporal_constraint.end_date is None
