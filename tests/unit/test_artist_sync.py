# tests/unit/test_artist_sync.py

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock

# Add the src directory to the path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from spotify_to_tidal.sync import artist_match, populate_artist_match_cache
from spotify_to_tidal.cache import ArtistMatchCache


class TestArtistMatching:
    """Test the artist matching functionality"""
    
    def test_exact_match(self):
        """Test exact artist name match"""
        # Mock Tidal artist
        tidal_artist = Mock()
        tidal_artist.name = "Radiohead"
        
        # Spotify artist
        spotify_artist = {"name": "Radiohead"}
        
        assert artist_match(tidal_artist, spotify_artist) == True
    
    def test_case_insensitive_match(self):
        """Test case insensitive matching"""
        tidal_artist = Mock()
        tidal_artist.name = "RADIOHEAD"
        
        spotify_artist = {"name": "radiohead"}
        
        assert artist_match(tidal_artist, spotify_artist) == True
    
    def test_substring_match(self):
        """Test substring matching"""
        tidal_artist = Mock()
        tidal_artist.name = "The Beatles"
        
        spotify_artist = {"name": "Beatles"}
        
        assert artist_match(tidal_artist, spotify_artist) == True
    
    def test_unicode_normalization(self):
        """Test unicode normalization"""
        tidal_artist = Mock()
        tidal_artist.name = "Sigur Rós"
        
        spotify_artist = {"name": "Sigur Ros"}
        
        assert artist_match(tidal_artist, spotify_artist) == True
    
    def test_with_parentheses_simplification(self):
        """Test matching with parentheses removal"""
        tidal_artist = Mock()
        tidal_artist.name = "Run-DMC"
        
        spotify_artist = {"name": "Run-DMC (Hip-Hop Legends)"}
        
        assert artist_match(tidal_artist, spotify_artist) == True
    
    def test_no_match(self):
        """Test when artists don't match"""
        tidal_artist = Mock()
        tidal_artist.name = "Radiohead"
        
        spotify_artist = {"name": "Coldplay"}
        
        assert artist_match(tidal_artist, spotify_artist) == False
    
    def test_fuzzy_matching_disabled(self):
        """Test fuzzy matching when disabled (default)"""
        tidal_artist = Mock()
        tidal_artist.name = "Radiohed"  # typo
        
        spotify_artist = {"name": "Radiohead"}
        
        assert artist_match(tidal_artist, spotify_artist) == False
    
    def test_fuzzy_matching_enabled(self):
        """Test fuzzy matching when enabled"""
        tidal_artist = Mock()
        tidal_artist.name = "Radiohed"  # typo but close enough
        
        spotify_artist = {"name": "Radiohead"}
        config = {"enable_fuzzy_matching": True, "fuzzy_name_threshold": 0.85}
        
        assert artist_match(tidal_artist, spotify_artist, config) == True
    
    def test_fuzzy_matching_below_threshold(self):
        """Test fuzzy matching below threshold"""
        tidal_artist = Mock()
        tidal_artist.name = "Completely Different Artist"
        
        spotify_artist = {"name": "Radiohead"}
        config = {"enable_fuzzy_matching": True, "fuzzy_name_threshold": 0.85}
        
        assert artist_match(tidal_artist, spotify_artist, config) == False


class TestArtistCaching:
    """Test the artist cache population functionality"""
    
    def test_artist_match_cache_insert(self):
        artist_cache = ArtistMatchCache()
        # Clear any existing data to ensure clean test state
        artist_cache.data = {}
        artist_cache.insert(("spotify_artist_id", "tidal_artist_id"))
        assert artist_cache.get("spotify_artist_id") == "tidal_artist_id"

    def test_artist_match_cache_get(self):
        artist_cache = ArtistMatchCache()
        # Clear any existing data to ensure clean test state
        artist_cache.data = {}
        artist_cache.insert(("spotify_artist_id", "tidal_artist_id"))
        assert artist_cache.get("spotify_artist_id") == "tidal_artist_id"
        assert artist_cache.get("nonexistent_id") is None

    def test_artist_match_cache_nonexistent_key(self):
        artist_cache = ArtistMatchCache()
        # Clear any existing data to ensure clean test state
        artist_cache.data = {}
        assert artist_cache.get("nonexistent_key") is None

    def test_artist_match_cache_multiple_operations(self):
        artist_cache = ArtistMatchCache()
        # Clear any existing data to ensure clean test state
        artist_cache.data = {}
        
        # Insert multiple entries
        artist_cache.insert(("spotify_1", "tidal_1"))
        artist_cache.insert(("spotify_2", "tidal_2"))
        artist_cache.insert(("spotify_3", "tidal_3"))
        
        # Verify all entries can be retrieved
        assert artist_cache.get("spotify_1") == "tidal_1"
        assert artist_cache.get("spotify_2") == "tidal_2"
        assert artist_cache.get("spotify_3") == "tidal_3"
        
        # Verify nonexistent keys still return None
        assert artist_cache.get("spotify_4") is None
        
        # Test overwriting an existing entry
        artist_cache.insert(("spotify_1", "new_tidal_1"))
        assert artist_cache.get("spotify_1") == "new_tidal_1"


class TestPopulateArtistMatchCache:
    """Test the artist cache population logic"""
    
    def test_populate_artist_match_cache_basic(self):
        """Test basic artist cache population"""
        # Clear the global cache for testing
        from spotify_to_tidal.cache import artist_match_cache
        artist_match_cache.data = {}
        
        # Mock Spotify artists
        spotify_artists = [
            {"id": "spotify_1", "name": "Radiohead"},
            {"id": "spotify_2", "name": "The Beatles"},
            {"id": "spotify_3", "name": "Led Zeppelin"}
        ]
        
        # Mock Tidal artists  
        tidal_artist_1 = Mock()
        tidal_artist_1.id = "tidal_1"
        tidal_artist_1.name = "Radiohead"
        
        tidal_artist_2 = Mock()
        tidal_artist_2.id = "tidal_2" 
        tidal_artist_2.name = "The Beatles"
        
        tidal_artist_3 = Mock()
        tidal_artist_3.id = "tidal_3"
        tidal_artist_3.name = "Pink Floyd"  # No match
        
        tidal_artists = [tidal_artist_1, tidal_artist_2, tidal_artist_3]
        
        # Populate cache
        populate_artist_match_cache(spotify_artists, tidal_artists)
        
        # Verify matches were cached
        assert artist_match_cache.get("spotify_1") == "tidal_1"  # Radiohead match
        assert artist_match_cache.get("spotify_2") == "tidal_2"  # Beatles match
        assert artist_match_cache.get("spotify_3") is None       # No match for Led Zeppelin
    
    def test_populate_artist_match_cache_no_duplicates(self):
        """Test that no duplicate matches are created"""
        # Clear the global cache for testing
        from spotify_to_tidal.cache import artist_match_cache
        artist_match_cache.data = {}
        
        # Mock data with potential duplicates
        spotify_artists = [
            {"id": "spotify_1", "name": "Radiohead"},
            {"id": "spotify_2", "name": "Radiohead"}  # Duplicate artist name
        ]
        
        tidal_artist = Mock()
        tidal_artist.id = "tidal_1"
        tidal_artist.name = "Radiohead"
        
        tidal_artists = [tidal_artist]
        
        # Populate cache
        populate_artist_match_cache(spotify_artists, tidal_artists)
        
        # Only one of the Spotify artists should be matched
        matched_count = sum(1 for spotify_id in ["spotify_1", "spotify_2"] 
                           if artist_match_cache.get(spotify_id) is not None)
        assert matched_count == 1
    
    def test_populate_artist_match_cache_empty_lists(self):
        """Test behavior with empty artist lists"""
        # Clear the global cache for testing
        from spotify_to_tidal.cache import artist_match_cache
        artist_match_cache.data = {}
        
        populate_artist_match_cache([], [])
        
        # Cache should remain empty
        assert len(artist_match_cache.data) == 0