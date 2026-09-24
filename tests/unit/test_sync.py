# tests/unit/test_sync.py

import asyncio

from spotify_to_tidal import sync


def test_extract_track_prefers_the_new_item_field():
    # the Spotify API renamed the playlist entry field from 'track' to 'item'
    entry = {"item": {"id": "new"}, "track": {"id": "legacy"}}
    assert sync._extract_track_from_spotify_item(entry)["id"] == "new"


def test_extract_track_falls_back_to_the_legacy_track_field():
    assert sync._extract_track_from_spotify_item({"track": {"id": "legacy"}})["id"] == "legacy"


def test_extract_track_returns_none_for_empty_entries():
    assert sync._extract_track_from_spotify_item({"item": None, "track": None}) is None


def test_fetch_all_handles_the_new_item_field():
    page = {
        "items": [{"item": {"id": "1"}}, {"item": None}],
        "next": None,
        "limit": 100,
        "total": 2,
    }
    tracks = asyncio.run(sync._fetch_all_from_spotify_in_chunks(lambda offset: page))
    assert [track["id"] for track in tracks] == ["1"]


def test_fetch_all_handles_the_legacy_track_field():
    page = {
        "items": [{"track": {"id": "1"}}, {"track": None}],
        "next": None,
        "limit": 100,
        "total": 2,
    }
    tracks = asyncio.run(sync._fetch_all_from_spotify_in_chunks(lambda offset: page))
    assert [track["id"] for track in tracks] == ["1"]
