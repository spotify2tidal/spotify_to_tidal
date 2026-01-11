# tests/unit/test_cache.py

import pytest
import datetime
import sqlalchemy
from sqlalchemy import create_engine, select
from unittest import mock
from spotify_to_tidal.cache import MatchFailureDatabase, TrackMatchCache, AlbumMatchCache


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


# Test AlbumMatchCache
def test_album_match_cache_insert():
    album_cache = AlbumMatchCache()
    # Clear any existing data to ensure clean test state
    album_cache.data = {}
    album_cache.insert(("spotify_album_id", "tidal_album_id"))
    assert album_cache.get("spotify_album_id") == "tidal_album_id"


def test_album_match_cache_get():
    album_cache = AlbumMatchCache()
    # Clear any existing data to ensure clean test state
    album_cache.data = {}
    album_cache.insert(("spotify_album_id", "tidal_album_id"))
    assert album_cache.get("spotify_album_id") == "tidal_album_id"
    assert album_cache.get("nonexistent_id") is None


def test_album_match_cache_nonexistent_key():
    album_cache = AlbumMatchCache()
    # Clear any existing data to ensure clean test state
    album_cache.data = {}
    assert album_cache.get("nonexistent_key") is None


def test_album_match_cache_multiple_operations():
    album_cache = AlbumMatchCache()
    # Clear any existing data to ensure clean test state
    album_cache.data = {}
    
    # Insert multiple entries
    album_cache.insert(("spotify_1", "tidal_1"))
    album_cache.insert(("spotify_2", "tidal_2"))
    album_cache.insert(("spotify_3", "tidal_3"))
    
    # Verify all entries can be retrieved
    assert album_cache.get("spotify_1") == "tidal_1"
    assert album_cache.get("spotify_2") == "tidal_2"
    assert album_cache.get("spotify_3") == "tidal_3"
    
    # Verify nonexistent keys still return None
    assert album_cache.get("spotify_4") is None
    
    # Test overwriting an existing entry
    album_cache.insert(("spotify_1", "new_tidal_1"))
    assert album_cache.get("spotify_1") == "new_tidal_1"