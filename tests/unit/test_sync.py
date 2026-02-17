from typing import Literal
from unittest.mock import MagicMock
import asyncio

from spotify_to_tidal.sync import isrc_match
from spotify_to_tidal.sync import _fetch_all_from_spotify_in_chunks
from spotify_to_tidal.sync import get_tracks_from_spotify_playlist
from spotify_to_tidal.sync import _get_tracks_from_spotify_favorites


def _make_tidal_track(isrc: str = 'USAT21234567') -> MagicMock:
    track = MagicMock()
    track.isrc = isrc
    return track


def _make_spotify_track(
    isrc: str = 'USAT21234567',
    name: str = 'Test Track',
    external_ids: bool = True,
) -> dict:
    """Build a minimal Spotify track dict."""
    track = {
        'name': name,
        'id': 'spotify123',
        'type': 'track',
        'duration_ms': 210000,
        'track_number': 1,
        'artists': [{'name': 'Test Artist'}],
        'album': {'name': 'Test Album', 'artists': [{'name': 'Test Artist'}]},
    }
    if external_ids:
        track['external_ids'] = {'isrc': isrc}
    return track

def _make_spotify_api_response(items, next_url=None, total=None, limit=50) -> dict:
    """Build a response dict matching Spotify's playlist items endpoint."""
    return {
        'items': items,
        'next': next_url,
        'total': total or len(items),
        'limit': limit,
    }


def _make_playlist_item(track_name: str = 'Test Track', item_type: Literal['track','episode']  = 'track') -> dict:
    """Build a single playlist item."""
    return {
        'item': {
            'name': track_name,
            'id': 'spotify123',
            'type': item_type,
            'duration_ms': 210000,
            'track_number': 1,
            'artists': [{'name': 'Test Artist'}],
            'album': {'name': 'Test Album', 'artists': [{'name': 'Test Artist'}]},
        },
        'type': item_type,
    }


def _make_saved_track_item(track_name: str = 'Test Track') -> dict:
    """Build a single saved track item matching current_user_saved_tracks response format."""
    return {
        'track': {
            'name': track_name,
            'id': 'spotify123',
            'type': 'track',
            'duration_ms': 210000,
            'track_number': 1,
            'artists': [{'name': 'Test Artist'}],
            'album': {'name': 'Test Album', 'artists': [{'name': 'Test Artist'}]},
        },
    }



class TestIsrcMatch:
    def test_matches_when_isrc_present_and_equal(self) -> None:
        tidal = _make_tidal_track(isrc='USAT21234567')
        spotify = _make_spotify_track(isrc='USAT21234567')
        assert isrc_match(tidal, spotify) is True

    def test_no_match_when_isrc_differs(self) -> None:
        tidal = _make_tidal_track(isrc='USAT21234567')
        spotify = _make_spotify_track(isrc='GBDCA0000001')
        assert isrc_match(tidal, spotify) is False

    def test_returns_false_when_external_ids_missing(self) -> None:
        tidal = _make_tidal_track()
        spotify = _make_spotify_track(external_ids=False)
        assert isrc_match(tidal, spotify) is False

    def test_returns_false_when_isrc_key_missing(self) -> None:
        tidal = _make_tidal_track()
        spotify = _make_spotify_track()
        spotify['external_ids'] = {}
        assert isrc_match(tidal, spotify) is False



class TestFetchAllFromSpotifyInChunks:
    def test_single_page(self) -> None:
        items = [_make_playlist_item('Track 1'), _make_playlist_item('Track 2')]
        response = _make_spotify_api_response(items)

        def fetch_fn(offset: int) -> dict:
            return response

        result = asyncio.run(_fetch_all_from_spotify_in_chunks(fetch_fn))
        assert len(result) == 1
        assert result[0] is response

    def test_multiple_pages(self) -> None:
        page1_items = [_make_playlist_item('Track 1')]
        page2_items = [_make_playlist_item('Track 2')]
        page1 = _make_spotify_api_response(
            page1_items, next_url='https://spotify.example.com/next', total=2, limit=1
        )
        page2 = _make_spotify_api_response(page2_items, total=2, limit=1)

        def fetch_fn(offset: int) -> dict:
            return page1 if offset == 0 else page2

        result = asyncio.run(_fetch_all_from_spotify_in_chunks(fetch_fn))
        assert len(result) == 2
        assert result[0] is page1
        assert result[1] is page2


class TestGetTracksFromSpotifyPlaylist:
    def test_filters_out_episodes(self) -> None:
        items = [
            _make_playlist_item('Track 1', item_type='track'),
            _make_playlist_item('Episode 1', item_type='episode'),
        ]
        response = _make_spotify_api_response(items)
        mock_session = MagicMock()
        mock_session.playlist_items.return_value = response
        spotify_playlist = {'name': 'My Playlist', 'id': 'playlist123'}

        result = asyncio.run(
            get_tracks_from_spotify_playlist(mock_session, spotify_playlist)
        )
        assert len(result) == 1
        assert result[0]['name'] == 'Track 1'


class TestGetTracksFromSpotifyFavorites:
    def test_extracts_tracks_from_saved_tracks_response(self) -> None:
        items = [
            _make_saved_track_item('Fav 1'),
            _make_saved_track_item('Fav 2'),
        ]
        response = _make_spotify_api_response(items)
        mock_session = MagicMock()
        mock_session.current_user_saved_tracks.return_value = response

        result = asyncio.run(_get_tracks_from_spotify_favorites(mock_session))
        assert len(result) == 2
        assert result[0]['name'] == 'Fav 2'
        assert result[1]['name'] == 'Fav 1'

    def test_filters_out_none_tracks(self) -> None:
        items = [_make_saved_track_item('Fav 1'), {'track': None}]
        response = _make_spotify_api_response(items)
        mock_session = MagicMock()
        mock_session.current_user_saved_tracks.return_value = response

        result = asyncio.run(_get_tracks_from_spotify_favorites(mock_session))
        assert len(result) == 1
        assert result[0]['name'] == 'Fav 1'

    def test_multiple_pages(self) -> None:
        page1 = _make_spotify_api_response(
            [_make_saved_track_item('Fav 1')],
            next_url='https://spotify.example.com/next', total=2, limit=1,
        )
        page2 = _make_spotify_api_response(
            [_make_saved_track_item('Fav 2')], total=2, limit=1,
        )
        mock_session = MagicMock()
        mock_session.current_user_saved_tracks.side_effect = lambda offset: page1 if offset == 0 else page2

        result = asyncio.run(_get_tracks_from_spotify_favorites(mock_session))
        assert len(result) == 2
        assert result[0]['name'] == 'Fav 2'
        assert result[1]['name'] == 'Fav 1'
