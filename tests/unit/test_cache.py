# tests/unit/test_cache.py

import pytest
import datetime
import sqlalchemy
from sqlalchemy import create_engine, select
from unittest import mock
from spotify_to_tidal.cache import MatchFailureDatabase, TrackMatchCache


# Setup an in-memory SQLite database for testing
@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    return engine


# Test MatchFailureDatabase
def test_cache_match_failure(in_memory_db, mocker):
    mocker.patch(
        "spotify_to_tidal.cache.sqlalchemy.create_engine", return_value=in_memory_db
    )
    failure_db = MatchFailureDatabase()

    track_id = "test_track"
    failure_db.cache_match_failure(track_id)

    with failure_db.engine.connect() as connection:
        result = connection.execute(
            select(failure_db.match_failures).where(
                failure_db.match_failures.c.track_id == track_id
            )
        ).fetchone()
        assert result is not None
        assert result.track_id == track_id


def test_has_match_failure(in_memory_db, mocker):
    mocker.patch(
        "spotify_to_tidal.cache.sqlalchemy.create_engine", return_value=in_memory_db
    )
    failure_db = MatchFailureDatabase()

    track_id = "test_track"
    failure_db.cache_match_failure(track_id)

    assert failure_db.has_match_failure(track_id) is True


def test_remove_match_failure(in_memory_db, mocker):
    mocker.patch(
        "spotify_to_tidal.cache.sqlalchemy.create_engine", return_value=in_memory_db
    )
    failure_db = MatchFailureDatabase()

    track_id = "test_track"
    failure_db.cache_match_failure(track_id)
    failure_db.remove_match_failure(track_id)

    with failure_db.engine.connect() as connection:
        result = connection.execute(
            select(failure_db.match_failures).where(
                failure_db.match_failures.c.track_id == track_id
            )
        ).fetchone()
        assert result is None


# Test TrackMatchCache
def test_track_match_cache_insert():
    track_cache = TrackMatchCache()
    track_cache.insert(("spotify_id", 123))
    assert track_cache.get("spotify_id") == 123


def test_track_match_cache_get():
    track_cache = TrackMatchCache()
    track_cache.insert(("spotify_id", 123))
    assert track_cache.get("spotify_id") == 123
    assert track_cache.get("nonexistent_id") is None