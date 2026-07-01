# tests/unit/test_playlist_add.py

import asyncio

import requests
import tidalapi

from spotify_to_tidal import tidalapi_patch as patch_mod


class _Resp412:
    status_code = 412
    text = "precondition failed"
    headers = {}


def _no_backoff(monkeypatch):
    """Skip the real asyncio.sleep backoff between 412 retries."""
    async def _sleep(_):
        pass
    monkeypatch.setattr(asyncio, "sleep", _sleep)


def test_add_tracks_retries_chunk_on_rate_limit_without_duplicates(monkeypatch):
    """A rate-limit error on one chunk retries only that chunk (via repeat_on_request_error) —
    earlier chunks are not re-added, which a whole-operation retry would have duplicated."""
    _no_backoff(monkeypatch)
    added = []
    calls = {"n": 0}

    class FakePlaylist:
        def _reparse(self):
            pass
        def add(self, chunk):
            calls["n"] += 1
            # fail the first attempt at the second chunk, succeed on retry
            if list(chunk) == [3, 4] and calls["n"] == 2:
                raise tidalapi.exceptions.TooManyRequests("rate limited")
            added.append(list(chunk))

    asyncio.run(patch_mod.add_tracks_to_tidal_playlist(FakePlaylist(), [1, 2, 3, 4, 5], chunk_size=2))

    # every track added exactly once, in order — no duplicate of the [1, 2] chunk
    assert added == [[1, 2], [3, 4], [5]]


def test_add_tracks_retries_chunk_on_412_after_refreshing_etag(monkeypatch):
    """A 412 on a chunk add refreshes the ETag (_reparse) and retries just that chunk (no dupes)."""
    _no_backoff(monkeypatch)
    added = []
    reparses = {"n": 0}

    class FakePlaylist:
        def __init__(self):
            self._calls = 0
        def _reparse(self):
            reparses["n"] += 1
        def add(self, chunk):
            self._calls += 1
            if list(chunk) == [3, 4] and self._calls == 2:  # 412 on first attempt of this chunk
                raise requests.exceptions.HTTPError(response=_Resp412())
            added.append(list(chunk))

    asyncio.run(patch_mod.add_tracks_to_tidal_playlist(FakePlaylist(), [1, 2, 3, 4, 5], chunk_size=2))

    assert added == [[1, 2], [3, 4], [5]]   # [3,4] added once, after the refresh+retry
    assert reparses["n"] >= 1               # refreshed the ETag on the 412 before retrying


def test_clear_tidal_playlist_removes_in_chunks(monkeypatch):
    """clear loops the library's remove_by_indices in chunks until the playlist is empty."""
    _no_backoff(monkeypatch)
    removed = []

    class FakePlaylist:
        def __init__(self):
            self.num_tracks = 13
        def _reparse(self):
            pass
        def remove_by_indices(self, indices):
            indices = list(indices)
            removed.append(indices)
            self.num_tracks -= len(indices)  # the library reparses after each delete, shrinking the list

    asyncio.run(patch_mod.clear_tidal_playlist(FakePlaylist(), chunk_size=5))

    assert [len(c) for c in removed] == [5, 5, 3]  # 13 tracks erased in chunks of 5


def test_clear_tidal_playlist_retries_delete_on_412(monkeypatch):
    """A 412 on a delete chunk refreshes the ETag and retries the delete rather than aborting."""
    _no_backoff(monkeypatch)
    reparses = {"n": 0}
    attempts = {"n": 0}

    class FakePlaylist:
        def __init__(self):
            self.num_tracks = 5
        def _reparse(self):
            reparses["n"] += 1
        def remove_by_indices(self, indices):
            attempts["n"] += 1
            if attempts["n"] == 1:  # first delete 412s, then succeeds after a refresh
                raise requests.exceptions.HTTPError(response=_Resp412())
            self.num_tracks -= len(list(indices))

    asyncio.run(patch_mod.clear_tidal_playlist(FakePlaylist()))

    assert attempts["n"] == 2  # first 412'd, retried after refresh
    assert reparses["n"] >= 1
