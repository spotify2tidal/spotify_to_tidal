# tests/unit/test_fetch_chunks.py

import asyncio

from spotify_to_tidal.sync import _fetch_all_from_spotify_in_chunks


def test_fetch_chunks_default_track_key_single_page():
    def fetch(offset):
        return {
            "items": [{"track": "t1"}, {"track": None}, {"track": "t2"}],
            "next": None,
            "limit": 3,
            "total": 3,
        }

    out = asyncio.run(_fetch_all_from_spotify_in_chunks(fetch))
    assert out == ["t1", "t2"]  # None items skipped


def test_fetch_chunks_album_key_with_pagination():
    pages = {
        0: {"items": [{"album": "a1"}, {"album": "a2"}], "next": "more", "limit": 2, "total": 3},
        2: {"items": [{"album": "a3"}], "next": None, "limit": 2, "total": 3},
    }

    out = asyncio.run(_fetch_all_from_spotify_in_chunks(lambda offset: pages[offset], item_key="album"))
    assert out == ["a1", "a2", "a3"]
