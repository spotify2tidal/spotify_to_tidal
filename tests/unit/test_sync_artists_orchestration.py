# tests/unit/test_sync_artists_orchestration.py
#
# Orchestration-level tests for the followed-artist sync flow. test_artist_sync.py covers
# artist_match and the match cache in isolation; these exercise the prepare / finish /
# resolve_residual_artists_on_tidal paths end to end: cursor pagination, the wanted-set
# computation, release-grounded residual resolution (found / not found), full-sync success,
# partial failure, skip-already-followed, add-retry, and the wrapper.

import asyncio
from unittest import mock

import pytest
import requests
import tidalapi

from spotify_to_tidal import sync as sync_mod
from spotify_to_tidal.cache import artist_match_cache


class DummyTidalArtist:
    def __init__(self, artist_id, name):
        self.id = artist_id
        self.name = name


class DummyRelease:
    """Stand-in for a matched tidalapi Track/Album: only .artists is read."""
    def __init__(self, artists):
        self.artists = artists


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Each test gets a clean match cache, not-found log, and empty wanted set."""
    artist_match_cache.data = {}
    sync_mod.clear_not_found_log()
    sync_mod.set_wanted_artist_ids(set())
    yield
    artist_match_cache.data = {}
    sync_mod.clear_not_found_log()
    sync_mod.set_wanted_artist_ids(set())


def _followed_page(items, after=None, has_next=False):
    return {
        "artists": {
            "items": items,
            "next": "https://api.spotify.com/next" if has_next else None,
            "cursors": {"after": after},
        }
    }


def _config():
    return {"max_concurrency": 10, "rate_limit": 10}


# --------------------------------------------------------------------------
# Fetching followed artists (cursor pagination), via the full sync_artists path
# --------------------------------------------------------------------------

def _run_sync_capturing_fetched(mocker, spotify_session):
    """Run sync_artists with the residual resolver stubbed out, returning the spotify artists
    that reached resolve_residual_artists_on_tidal (i.e. what prepare fetched)."""
    captured = {"artists": None}

    def _capture_resolve(spotify_session, tidal_session, spotify_artists, config):
        captured["artists"] = list(spotify_artists)

    mocker.patch.object(sync_mod, "get_all_saved_artists", return_value=[])
    mocker.patch.object(sync_mod, "resolve_residual_artists_on_tidal", side_effect=_capture_resolve)
    mocker.patch.object(sync_mod, "add_artist_to_tidal_collection")
    mocker.patch.object(sync_mod, "tqdm", side_effect=lambda x, **kwargs: x)

    asyncio.run(sync_mod.sync_artists(spotify_session, mock.MagicMock(), _config()))
    return captured["artists"]


def test_get_followed_artists_single_page(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "a1", "name": "Artist One"}, {"id": "a2", "name": "Artist Two"}]
    )

    fetched = _run_sync_capturing_fetched(mocker, spotify_session)

    assert [a["name"] for a in fetched] == ["Artist One", "Artist Two"]
    spotify_session.current_user_followed_artists.assert_called_once_with(limit=50)


def test_get_followed_artists_multiple_pages(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.side_effect = [
        _followed_page(
            [{"id": "a1", "name": "Artist One"}, {"id": "a2", "name": "Artist Two"}],
            after="xyz", has_next=True,
        ),
        _followed_page([{"id": "a3", "name": "Artist Three"}]),
    ]

    fetched = _run_sync_capturing_fetched(mocker, spotify_session)

    assert [a["id"] for a in fetched] == ["a1", "a2", "a3"]
    assert spotify_session.current_user_followed_artists.call_count == 2
    assert spotify_session.current_user_followed_artists.call_args_list[1] == mock.call(limit=50, after="xyz")


def test_get_followed_artists_empty(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page([])

    mocker.patch.object(sync_mod, "get_all_saved_artists", return_value=[])
    mocker.patch.object(sync_mod, "resolve_residual_artists_on_tidal")
    mocker.patch.object(sync_mod, "tqdm", side_effect=lambda x, **kwargs: x)
    add_mock = mocker.patch.object(sync_mod, "add_artist_to_tidal_collection")

    asyncio.run(sync_mod.sync_artists(spotify_session, mock.MagicMock(), _config()))

    add_mock.assert_not_called()


# --------------------------------------------------------------------------
# prepare: wanted-set computation
# --------------------------------------------------------------------------

def test_prepare_excludes_already_followed_from_wanted(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}, {"id": "sp2", "name": "Artist Two"}]
    )
    mocker.patch.object(sync_mod, "get_all_saved_artists", return_value=[DummyTidalArtist(101, "Artist One")])

    sync_mod.prepare_artist_sync_wrapper(spotify_session, mock.MagicMock(), _config())

    # sp1 already followed on Tidal -> resolved into the cache and excluded from `wanted`
    assert artist_match_cache.get("sp1") == 101
    assert sync_mod._wanted_artist_ids == {"sp2"}


# --------------------------------------------------------------------------
# resolve_residual_artists_on_tidal: release-grounded (replaces the old name search)
# --------------------------------------------------------------------------

def test_resolve_residual_grounds_artist_via_top_track(mocker):
    sync_mod.set_wanted_artist_ids({"sp1"})
    spotify_session = mock.MagicMock()
    top_track = {"id": "t1", "name": "Song", "artists": [{"id": "sp1", "name": "Artist One"}]}
    spotify_session.artist_top_tracks.return_value = {"tracks": [top_track]}
    # the top track matches a real Tidal track whose artist (id 901) is the grounded answer
    mocker.patch.object(sync_mod, "tidal_search",
                        new=mock.AsyncMock(return_value=DummyRelease([DummyTidalArtist(901, "Artist One")])))

    spotify_artists = [{"id": "sp1", "name": "Artist One"}]
    asyncio.run(sync_mod.resolve_residual_artists_on_tidal(spotify_session, mock.MagicMock(), spotify_artists, _config()))

    assert artist_match_cache.get("sp1") == 901  # id read off the matched release, not a name guess


def test_resolve_residual_logs_and_skips_when_no_top_track_matches(mocker):
    sync_mod.set_wanted_artist_ids({"sp1"})
    spotify_session = mock.MagicMock()
    spotify_session.artist_top_tracks.return_value = {
        "tracks": [{"id": "t1", "name": "Song", "artists": [{"id": "sp1", "name": "Artist One"}]}]
    }
    mocker.patch.object(sync_mod, "tidal_search", new=mock.AsyncMock(return_value=None))  # nothing matches

    spotify_artists = [{"id": "sp1", "name": "Artist One"}]
    asyncio.run(sync_mod.resolve_residual_artists_on_tidal(spotify_session, mock.MagicMock(), spotify_artists, _config()))

    assert artist_match_cache.get("sp1") is None  # ungrounded -> not resolved
    assert any(i["type"] == "artist" and i["info"] == "Artist One" for i in sync_mod._not_found_items)


# --------------------------------------------------------------------------
# Full sync_artists orchestration
# --------------------------------------------------------------------------

def _patch_sync_artists(mocker, found_map, existing_tidal=None):
    """Stub get_all_saved_artists + the residual resolver so that artists in found_map get a
    cache entry (spotify_id -> tidal_id) as if grounded on Tidal."""
    mocker.patch.object(sync_mod, "get_all_saved_artists", return_value=existing_tidal or [])

    def _resolve(spotify_session, tidal_session, spotify_artists, config):
        for artist in spotify_artists:
            if artist["id"] in found_map and not artist_match_cache.get(artist["id"]):
                artist_match_cache.insert((artist["id"], found_map[artist["id"]]))

    mocker.patch.object(sync_mod, "resolve_residual_artists_on_tidal", side_effect=_resolve)
    mocker.patch.object(sync_mod, "tqdm", side_effect=lambda x, **kwargs: x)


def test_sync_artists_success(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}, {"id": "sp2", "name": "Artist Two"}]
    )
    _patch_sync_artists(mocker, found_map={"sp1": 101, "sp2": 202})

    tidal_session = mock.MagicMock()
    asyncio.run(sync_mod.sync_artists(spotify_session, tidal_session, _config()))

    assert tidal_session.user.favorites.add_artist.call_count == 2
    assert {c.args[0] for c in tidal_session.user.favorites.add_artist.call_args_list} == {101, 202}


def test_sync_artists_partial_failure(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}, {"id": "sp2", "name": "Nonexistent Artist"}]
    )
    _patch_sync_artists(mocker, found_map={"sp1": 101})  # only sp1 can be grounded

    tidal_session = mock.MagicMock()
    asyncio.run(sync_mod.sync_artists(spotify_session, tidal_session, _config()))

    tidal_session.user.favorites.add_artist.assert_called_once_with(101)


def test_sync_artists_skips_already_followed(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}]
    )
    # already followed on Tidal (id 101) -> resolved in prepare, excluded from wanted, not re-followed
    _patch_sync_artists(mocker, found_map={"sp1": 101}, existing_tidal=[DummyTidalArtist(101, "Artist One")])

    tidal_session = mock.MagicMock()
    asyncio.run(sync_mod.sync_artists(spotify_session, tidal_session, _config()))

    tidal_session.user.favorites.add_artist.assert_not_called()


def test_sync_artists_add_retries_on_rate_limit(mocker):
    async def _no_sleep(delay):  # the retry backs off via asyncio.sleep; skip the real wait
        pass
    mocker.patch.object(asyncio, "sleep", _no_sleep)
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}]
    )
    _patch_sync_artists(mocker, found_map={"sp1": 101})

    tidal_session = mock.MagicMock()
    tidal_session.user.favorites.add_artist.side_effect = [
        tidalapi.exceptions.TooManyRequests("rate limited"),  # first attempt fails
        None,  # retry succeeds
    ]

    asyncio.run(sync_mod.sync_artists(spotify_session, tidal_session, _config()))

    assert tidal_session.user.favorites.add_artist.call_count == 2
    assert all(c.args[0] == 101 for c in tidal_session.user.favorites.add_artist.call_args_list)


def test_sync_artists_add_non_retryable_error_propagates(mocker):
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}]
    )
    _patch_sync_artists(mocker, found_map={"sp1": 101})

    tidal_session = mock.MagicMock()
    tidal_session.user.favorites.add_artist.side_effect = ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(sync_mod.sync_artists(spotify_session, tidal_session, _config()))
    tidal_session.user.favorites.add_artist.assert_called_once_with(101)


def test_sync_artists_follow_continues_on_per_item_http_error(mocker):
    # one artist's follow returns 404 (e.g. invalid/region-unavailable id) — it must be logged and
    # skipped, not abort the whole follow batch.
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page(
        [{"id": "sp1", "name": "Artist One"}, {"id": "sp2", "name": "Artist Two"}]
    )
    _patch_sync_artists(mocker, found_map={"sp1": 101, "sp2": 202})

    class _Resp404:
        status_code = 404
        text = "not found"
        headers = {}

    def _add(artist_id):
        if artist_id == 101:
            raise requests.exceptions.HTTPError(response=_Resp404())

    tidal_session = mock.MagicMock()
    tidal_session.user.favorites.add_artist.side_effect = _add

    asyncio.run(sync_mod.sync_artists(spotify_session, tidal_session, _config()))

    # both follows attempted (the 404 on 101 didn't abort the batch); 101 logged as not-found
    assert tidal_session.user.favorites.add_artist.call_count == 2
    assert any(i["type"] == "artist" and "101" in i["info"] for i in sync_mod._not_found_items)


def test_sync_artists_wrapper(mocker):
    mock_sync = mocker.patch.object(sync_mod, "sync_artists")

    sync_mod.sync_artists_wrapper(mock.MagicMock(), mock.MagicMock(), _config())

    mock_sync.assert_called_once()
