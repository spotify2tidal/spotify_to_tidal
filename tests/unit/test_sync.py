import pytest
import asyncio
from unittest import mock
from spotify_to_tidal.sync import (
    get_followed_artists_from_spotify,
    search_artist_on_tidal,
    sync_artists,
)


@pytest.fixture
def mock_spotify_session():
    """Create a mock Spotify session"""
    session = mock.MagicMock()
    return session


@pytest.fixture
def mock_tidal_session():
    """Create a mock Tidal session"""
    session = mock.MagicMock()
    session.user.favorites.add_artist = mock.MagicMock()
    return session


@pytest.fixture
def mock_config():
    """Create a mock config"""
    return {
        "max_concurrency": 10,
        "rate_limit": 10,
    }


@pytest.fixture
def sample_spotify_artists():
    """Sample Spotify artists response"""
    return {
        "artists": {
            "items": [
                {"id": "artist1", "name": "Artist One"},
                {"id": "artist2", "name": "Artist Two"},
            ],
            "next": None,
            "cursors": {"after": None},
        }
    }


@pytest.fixture
def sample_spotify_artists_paginated():
    """Sample Spotify artists response with pagination"""
    return [
        {
            "artists": {
                "items": [
                    {"id": "artist1", "name": "Artist One"},
                    {"id": "artist2", "name": "Artist Two"},
                ],
                "next": "https://api.spotify.com/v1/me/following?type=artist&limit=20&after=xyz",
                "cursors": {"after": "xyz"},
            }
        },
        {
            "artists": {
                "items": [
                    {"id": "artist3", "name": "Artist Three"},
                ],
                "next": None,
                "cursors": {"after": None},
            }
        },
    ]


@pytest.fixture
def sample_tidal_artist():
    """Sample Tidal artist object"""
    artist = mock.MagicMock()
    artist.id = 12345
    artist.name = "Artist One"
    return artist


def test_get_followed_artists_single_page(mock_spotify_session, sample_spotify_artists):
    """Test fetching artists from Spotify (single page)"""
    mock_spotify_session.current_user_followed_artists.return_value = sample_spotify_artists

    async def _test():
        artists = await get_followed_artists_from_spotify(mock_spotify_session)
        assert len(artists) == 2
        assert artists[0]["name"] == "Artist One"
        assert artists[1]["name"] == "Artist Two"
        mock_spotify_session.current_user_followed_artists.assert_called_once_with(after=None)

    asyncio.run(_test())


def test_get_followed_artists_multiple_pages(mock_spotify_session, sample_spotify_artists_paginated):
    """Test fetching artists from Spotify (multiple pages)"""
    mock_spotify_session.current_user_followed_artists.side_effect = sample_spotify_artists_paginated

    async def _test():
        artists = await get_followed_artists_from_spotify(mock_spotify_session)
        assert len(artists) == 3
        assert artists[0]["name"] == "Artist One"
        assert artists[1]["name"] == "Artist Two"
        assert artists[2]["name"] == "Artist Three"
        assert mock_spotify_session.current_user_followed_artists.call_count == 2

    asyncio.run(_test())


def test_get_followed_artists_empty(mock_spotify_session):
    """Test fetching artists when user has no followed artists"""
    mock_spotify_session.current_user_followed_artists.return_value = {
        "artists": {
            "items": [],
            "next": None,
            "cursors": {"after": None},
        }
    }

    async def _test():
        artists = await get_followed_artists_from_spotify(mock_spotify_session)
        assert len(artists) == 0

    asyncio.run(_test())


def test_search_artist_on_tidal_found(mock_tidal_session, sample_tidal_artist):
    """Test searching for an artist on Tidal (found)"""
    mock_tidal_session.search.return_value = {
        "artists": [sample_tidal_artist]
    }

    async def _test():
        artist = await search_artist_on_tidal("Artist One", mock_tidal_session)
        assert artist is not None
        assert artist.id == 12345
        mock_tidal_session.search.assert_called_once()

    asyncio.run(_test())


def test_search_artist_on_tidal_not_found(mock_tidal_session):
    """Test searching for an artist on Tidal (not found)"""
    mock_tidal_session.search.return_value = {"artists": []}

    async def _test():
        artist = await search_artist_on_tidal("Nonexistent Artist", mock_tidal_session)
        assert artist is None
        mock_tidal_session.search.assert_called_once()

    asyncio.run(_test())


def test_sync_artists_success(mock_spotify_session, mock_tidal_session, mock_config, sample_tidal_artist, mocker):
    """Test successful artist syncing"""
    mock_get_artists = mocker.patch(
        "spotify_to_tidal.sync.get_followed_artists_from_spotify",
        return_value=[
            {"id": "artist1", "name": "Artist One"},
            {"id": "artist2", "name": "Artist Two"},
        ],
    )
    mock_search = mocker.patch(
        "spotify_to_tidal.sync.search_artist_on_tidal",
        return_value=sample_tidal_artist,
    )
    mocker.patch("spotify_to_tidal.sync.tqdm", side_effect=lambda x, **kwargs: x)

    async def _test():
        await sync_artists(mock_spotify_session, mock_tidal_session, mock_config)
        mock_get_artists.assert_called_once()
        assert mock_search.call_count == 2
        assert mock_tidal_session.user.favorites.add_artist.call_count == 2

    asyncio.run(_test())


def test_sync_artists_no_artists(mock_spotify_session, mock_tidal_session, mock_config, mocker):
    """Test syncing when user has no followed artists"""
    mocker.patch(
        "spotify_to_tidal.sync.get_followed_artists_from_spotify",
        return_value=[],
    )

    async def _test():
        await sync_artists(mock_spotify_session, mock_tidal_session, mock_config)
        mock_tidal_session.user.favorites.add_artist.assert_not_called()

    asyncio.run(_test())


def test_sync_artists_partial_failure(mock_spotify_session, mock_tidal_session, mock_config, sample_tidal_artist, mocker):
    """Test artist syncing with some artists not found"""
    mocker.patch(
        "spotify_to_tidal.sync.get_followed_artists_from_spotify",
        return_value=[
            {"id": "artist1", "name": "Artist One"},
            {"id": "artist2", "name": "Nonexistent Artist"},
        ],
    )
    
    mock_search = mocker.patch(
        "spotify_to_tidal.sync.search_artist_on_tidal",
        side_effect=[sample_tidal_artist, None],
    )
    mocker.patch("spotify_to_tidal.sync.tqdm", side_effect=lambda x, **kwargs: x)

    async def _test():
        await sync_artists(mock_spotify_session, mock_tidal_session, mock_config)
        assert mock_search.call_count == 2
        assert mock_tidal_session.user.favorites.add_artist.call_count == 1

    asyncio.run(_test())


def test_sync_artists_add_artist_failure(mock_spotify_session, mock_tidal_session, mock_config, sample_tidal_artist, mocker):
    """Test artist syncing when adding to favorites fails"""
    mocker.patch(
        "spotify_to_tidal.sync.get_followed_artists_from_spotify",
        return_value=[
            {"id": "artist1", "name": "Artist One"},
        ],
    )
    
    mocker.patch(
        "spotify_to_tidal.sync.search_artist_on_tidal",
        return_value=sample_tidal_artist,
    )
    
    mock_tidal_session.user.favorites.add_artist.side_effect = Exception("API Error")
    mocker.patch("spotify_to_tidal.sync.tqdm", side_effect=lambda x, **kwargs: x)

    async def _test():
        await sync_artists(mock_spotify_session, mock_tidal_session, mock_config)
        mock_tidal_session.user.favorites.add_artist.assert_called_once()

    asyncio.run(_test())


def test_sync_artists_search_error(mock_spotify_session, mock_tidal_session, mock_config, mocker):
    """Test artist syncing when search raises an exception"""
    mocker.patch(
        "spotify_to_tidal.sync.get_followed_artists_from_spotify",
        return_value=[
            {"id": "artist1", "name": "Artist One"},
        ],
    )
    
    mock_search = mocker.patch(
        "spotify_to_tidal.sync.search_artist_on_tidal",
        side_effect=Exception("Search Error"),
    )
    mocker.patch("spotify_to_tidal.sync.tqdm", side_effect=lambda x, **kwargs: x)

    async def _test():
        await sync_artists(mock_spotify_session, mock_tidal_session, mock_config)
        mock_search.assert_called_once()

    asyncio.run(_test())


def test_sync_artists_wrapper(mock_spotify_session, mock_tidal_session, mock_config, mocker):
    """Test the sync_artists_wrapper function"""
    mock_sync = mocker.patch("spotify_to_tidal.sync.sync_artists")

    from spotify_to_tidal.sync import sync_artists_wrapper

    sync_artists_wrapper(mock_spotify_session, mock_tidal_session, mock_config)

    mock_sync.assert_called_once()
