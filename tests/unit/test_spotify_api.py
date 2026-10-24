import asyncio
from unittest.mock import Mock

import pytest

from spotify_to_tidal import sync


@pytest.mark.parametrize('track_key', ['track', 'item'])
def test_spotify_track_formats_and_pagination(track_key):
    first = {'id': 'first'}
    second = {'id': 'second'}
    pages = {
        0: {'items': [{track_key: first}, {track_key: None}], 'next': 'next-page', 'limit': 2, 'total': 3},
        2: {'items': [{track_key: second}], 'next': None, 'limit': 2, 'total': 3},
    }
    assert asyncio.run(sync._fetch_all_from_spotify_in_chunks(pages.__getitem__)) == [first, second]


@pytest.mark.parametrize('track_key', ['track', 'item'])
def test_spotify_playlist_request_preserves_item_metadata(track_key):
    session = Mock()
    track = {'id': 'song', 'type': 'track', 'album': {'name': 'Album', 'artists': [{'name': 'Artist'}]}}
    session.playlist_tracks.return_value = {'items': [{track_key: track}], 'next': None}
    assert asyncio.run(sync.get_tracks_from_spotify_playlist(session, {'id': 'source', 'name': 'Road Trip'})) == [track]
    session.playlist_tracks.assert_called_once_with(playlist_id='source', offset=0)