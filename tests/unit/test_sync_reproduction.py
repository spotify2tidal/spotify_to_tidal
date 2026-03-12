import pytest
import asyncio
from unittest.mock import MagicMock
from spotify_to_tidal.sync import _fetch_all_from_spotify_in_chunks, isrc_match

@pytest.mark.asyncio
async def test_fetch_all_from_spotify_in_chunks_playlist_format():
    """Test handling of the new 'item' format used in playlists (February 2026 update)."""
    # Mock response from Spotify for a playlist
    # New format: items[i]['item']
    mock_results = {
        'items': [
            {'item': {'name': 'Track 1', 'id': '1', 'type': 'track'}},
            {'item': {'name': 'Track 2', 'id': '2', 'type': 'track'}},
            {'item': None} # Should be filtered out
        ],
        'next': None,
        'limit': 100,
        'total': 2
    }
    
    fetch_function = MagicMock(return_value=mock_results)
    
    # This should currently fail with KeyError: 'track'
    try:
        tracks = await _fetch_all_from_spotify_in_chunks(fetch_function)
        assert len(tracks) == 2
        assert tracks[0]['name'] == 'Track 1'
    except KeyError as e:
        pytest.fail(f"KeyError: {e}")

@pytest.mark.asyncio
async def test_fetch_all_from_spotify_in_chunks_favorites_format():
    """Test handling of the old 'track' format used in favorites (me/tracks)."""
    # Old format: items[i]['track']
    mock_results = {
        'items': [
            {'track': {'name': 'Fav 1', 'id': 'f1', 'type': 'track'}},
            {'track': {'name': 'Fav 2', 'id': 'f2', 'type': 'track'}},
        ],
        'next': None,
        'limit': 100,
        'total': 2
    }
    
    fetch_function = MagicMock(return_value=mock_results)
    
    tracks = await _fetch_all_from_spotify_in_chunks(fetch_function)
    assert len(tracks) == 2
    assert tracks[0]['name'] == 'Fav 1'

def test_isrc_match_safe():
    """Test that isrc_match handles missing external_ids or isrc safely."""
    class MockTidalTrack:
        def __init__(self, isrc):
            self.isrc = isrc
            
    tidal_track = MockTidalTrack("US123")
    
    # Case 1: Missing external_ids
    assert isrc_match(tidal_track, {"name": "Track"}) is False
    
    # Case 2: Missing isrc in external_ids
    assert isrc_match(tidal_track, {"external_ids": {}}) is False
    
    # Case 3: Matching ISRC
    assert isrc_match(tidal_track, {"external_ids": {"isrc": "US123"}}) is True
