# tests/unit/test_artist_harvest.py
#
# Tests for release-grounded artist resolution: record_artist_matches_from_release harvests a
# followed artist's Tidal id off an already-matched track/album, filtered to the `wanted` set,
# and the prepare -> harvest -> finish flow follows it without any name search / top-tracks fetch.

from unittest import mock

import pytest

from spotify_to_tidal import sync as sync_mod
from spotify_to_tidal.sync import record_artist_matches_from_release
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
    artist_match_cache.data = {}
    sync_mod.clear_not_found_log()
    sync_mod.set_wanted_artist_ids(set())
    yield
    artist_match_cache.data = {}
    sync_mod.clear_not_found_log()
    sync_mod.set_wanted_artist_ids(set())


def _followed_page(items):
    return {"artists": {"items": items, "next": None, "cursors": {"after": None}}}


def _config():
    return {"max_concurrency": 10, "rate_limit": 10}


def test_harvest_records_only_wanted_artist_from_multi_artist_release():
    sync_mod.set_wanted_artist_ids({"sp_A"})  # we follow A but not the co-artist B
    release = {"id": "t1", "name": "Song",
               "artists": [{"id": "sp_A", "name": "Artist A"}, {"id": "sp_B", "name": "Artist B"}]}
    tidal = DummyRelease([DummyTidalArtist(902, "Artist B"), DummyTidalArtist(901, "Artist A")])

    record_artist_matches_from_release(release, tidal)

    assert artist_match_cache.get("sp_A") == 901
    assert artist_match_cache.get("sp_B") is None  # non-wanted co-artist ignored (concern iii)


def test_harvest_is_noop_when_nothing_wanted():
    release = {"artists": [{"id": "sp_A", "name": "Artist A"}]}
    record_artist_matches_from_release(release, DummyRelease([DummyTidalArtist(901, "Artist A")]))
    assert artist_match_cache.data == {}  # no wanted set -> zero overhead, nothing recorded


def test_harvest_disambiguates_via_the_release():
    sync_mod.set_wanted_artist_ids({"sp_js"})
    release = {"id": "al1", "name": "Record", "artists": [{"id": "sp_js", "name": "John Smith"}]}
    record_artist_matches_from_release(release, DummyRelease([DummyTidalArtist(555, "John Smith")]))
    assert artist_match_cache.get("sp_js") == 555  # the "John Smith" actually on the matched release


def test_harvest_skips_artists_without_id():
    sync_mod.set_wanted_artist_ids({"sp_A"})
    record_artist_matches_from_release({"artists": [{"name": "No Id Artist"}]},
                                       DummyRelease([DummyTidalArtist(901, "No Id Artist")]))
    assert artist_match_cache.data == {}


def test_harvest_does_not_overwrite_existing_mapping():
    sync_mod.set_wanted_artist_ids({"sp_A"})
    artist_match_cache.insert(("sp_A", 111))  # already resolved (e.g. from an ISRC-matched track)
    record_artist_matches_from_release({"artists": [{"id": "sp_A", "name": "A"}]},
                                       DummyRelease([DummyTidalArtist(901, "A")]))
    assert artist_match_cache.get("sp_A") == 111  # unchanged


def test_harvest_tolerates_missing_or_nonlist_artists():
    sync_mod.set_wanted_artist_ids({"sp_A"})
    record_artist_matches_from_release({"artists": [{"id": "sp_A", "name": "A"}]}, DummyRelease(None))
    record_artist_matches_from_release({"artists": [{"id": "sp_A", "name": "A"}]}, object())
    assert artist_match_cache.data == {}


def test_prepare_then_harvest_then_finish_follows_without_grounding(mocker):
    # Full library-grounded path: prepare computes `wanted`, the track/album sync harvests the
    # artist's Tidal id, and finish follows it WITHOUT any top-tracks fetch or name search.
    spotify_session = mock.MagicMock()
    spotify_session.current_user_followed_artists.return_value = _followed_page([{"id": "sp1", "name": "Artist One"}])
    mocker.patch.object(sync_mod, "get_all_saved_artists", return_value=[])
    mocker.patch.object(sync_mod, "tqdm", side_effect=lambda x, **kwargs: x)
    tidal_session = mock.MagicMock()

    spotify_artists, old = sync_mod.prepare_artist_sync_wrapper(spotify_session, tidal_session, _config())
    assert sync_mod._wanted_artist_ids == {"sp1"}

    # simulate the library harvest resolving sp1 during the track/album sync phase
    artist_match_cache.insert(("sp1", 777))

    sync_mod.finish_artist_sync_wrapper(spotify_session, tidal_session, _config(), spotify_artists, old)

    spotify_session.artist_top_tracks.assert_not_called()          # resolved for free, no grounding fetch
    tidal_session.user.favorites.add_artist.assert_called_once_with(777)
