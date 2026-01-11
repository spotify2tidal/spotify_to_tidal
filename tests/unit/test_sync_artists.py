import asyncio


class DummyTidalArtist:
    def __init__(self, artist_id: int, name: str):
        self.id = artist_id
        self.name = name


def test_pick_best_tidal_artist_match_exact_key():
    from spotify_to_tidal.sync import pick_best_tidal_artist_match

    spotify_artist = {"id": "sp1", "name": "Beyoncé"}
    candidates = [
        DummyTidalArtist(1, "Beyonce"),
        DummyTidalArtist(2, "Beyonce Knowles"),
    ]
    picked = pick_best_tidal_artist_match(spotify_artist, candidates, threshold=0.99)
    assert picked is candidates[0]


def test_pick_best_tidal_artist_match_threshold_rejects():
    from spotify_to_tidal.sync import pick_best_tidal_artist_match

    spotify_artist = {"id": "sp1", "name": "A Completely Unique Name"}
    candidates = [DummyTidalArtist(1, "Different Artist")]
    picked = pick_best_tidal_artist_match(spotify_artist, candidates, threshold=0.95)
    assert picked is None


def test_get_followed_artists_from_spotify_cursor_pagination_dedupes():
    from spotify_to_tidal.sync import get_followed_artists_from_spotify

    class DummySpotify:
        def __init__(self):
            self.calls = []

        def current_user_followed_artists(self, limit=50, after=None):
            self.calls.append((limit, after))
            if after is None:
                return {
                    "artists": {
                        "items": [{"id": "a1", "name": "A"}, {"id": "a2", "name": "B"}],
                        "cursors": {"after": "next"},
                        "next": "yes",
                    }
                }
            return {
                "artists": {
                    "items": [{"id": "a2", "name": "B"}, {"id": "a3", "name": "C"}],
                    "cursors": {"after": None},
                    "next": None,
                }
            }

    artists = asyncio.run(get_followed_artists_from_spotify(DummySpotify()))
    assert [a["id"] for a in artists] == ["a1", "a2", "a3"]


def test_sync_followed_artists_adds_missing_only(mocker):
    """
    Minimal integration-style unit test using mocks:
    - Spotify returns two followed artists
    - Tidal already has one favorited
    - Search finds matching artists for both
    - Only the missing one gets favorited
    """
    from spotify_to_tidal import sync as sync_mod

    spotify_artists = [{"id": "sp1", "name": "Artist One"}, {"id": "sp2", "name": "Artist Two"}]

    mocker.patch.object(sync_mod, "get_followed_artists_from_spotify", autospec=True, return_value=spotify_artists)
    mocker.patch.object(sync_mod, "get_all_favorite_artists", autospec=True, return_value=[DummyTidalArtist(101, "Artist One")])

    async def fake_tidal_search_artist(spotify_artist, rate_limiter, tidal_session, search_limit, search_delay=0.0):
        if spotify_artist["id"] == "sp1":
            return [DummyTidalArtist(101, "Artist One")]
        return [DummyTidalArtist(202, "Artist Two")]

    mocker.patch.object(sync_mod, "tidal_search_artist", autospec=True, side_effect=fake_tidal_search_artist)

    class DummyFavorites:
        def __init__(self):
            self.added = []

        def add_artist(self, artist_id):
            self.added.append(artist_id)

    class DummyUser:
        def __init__(self):
            self.favorites = DummyFavorites()

    class DummyTidalSession:
        def __init__(self):
            self.user = DummyUser()

    tidal = DummyTidalSession()
    asyncio.run(sync_mod.sync_followed_artists(spotify_session=object(), tidal_session=tidal, config={"max_concurrency": 2, "rate_limit": 10, "artist_match_threshold": 0.5}))
    assert tidal.user.favorites.added == [202]


