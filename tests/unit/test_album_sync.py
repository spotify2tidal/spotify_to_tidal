import pytest
import sys
from pathlib import Path

# Add the src directory to the path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from spotify_to_tidal.sync import album_match, populate_album_match_cache
from spotify_to_tidal.cache import album_match_cache


class MockTidalAlbum:
    """Mock Tidal album for testing"""
    def __init__(self, name, artists=None, album_id="12345"):
        self.name = name
        self.artists = [MockTidalArtist(artist) for artist in (artists or [])]
        self.id = album_id


class MockTidalArtist:
    """Mock Tidal artist for testing"""
    def __init__(self, name):
        self.name = name


class TestAlbumMatching:
    """Test album matching functionality"""
    
    @pytest.fixture
    def config_with_fuzzy(self):
        return {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80
        }
    
    @pytest.fixture
    def config_without_fuzzy(self):
        return {
            'enable_fuzzy_matching': False
        }
    
    def test_exact_album_match(self, config_with_fuzzy, config_without_fuzzy):
        """Test that exact album matches work with both configs"""
        tidal_album = MockTidalAlbum("OK Computer", ["Radiohead"])
        spotify_album = {
            "name": "OK Computer",
            "artists": [{"name": "Radiohead"}]
        }
        
        assert album_match(tidal_album, spotify_album, config_with_fuzzy)
        assert album_match(tidal_album, spotify_album, config_without_fuzzy)
    
    def test_fuzzy_album_name_match(self, config_with_fuzzy, config_without_fuzzy):
        """Test fuzzy matching for album names with minor typos"""
        tidal_album = MockTidalAlbum("OK Computer", ["Radiohead"])
        spotify_album = {
            "name": "OK Komputer",  # Minor typo that should fuzzy match
            "artists": [{"name": "Radiohead"}]
        }
        
        # Should match with fuzzy enabled but not without
        assert album_match(tidal_album, spotify_album, config_with_fuzzy)
        assert not album_match(tidal_album, spotify_album, config_without_fuzzy)
    
    def test_album_artist_mismatch(self, config_with_fuzzy):
        """Test that albums with different artists don't match"""
        tidal_album = MockTidalAlbum("OK Computer", ["Radiohead"])
        spotify_album = {
            "name": "OK Computer", 
            "artists": [{"name": "Coldplay"}]  # Different artist
        }
        
        # Should not match even with same name due to artist mismatch
        assert not album_match(tidal_album, spotify_album, config_with_fuzzy)
    
    def test_album_name_normalization(self, config_with_fuzzy):
        """Test that unicode normalization works for album names"""
        tidal_album = MockTidalAlbum("Ágætis byrjun", ["Sigur Rós"])
        spotify_album = {
            "name": "Agaetis byrjun",  # Without special characters
            "artists": [{"name": "Sigur Ros"}]
        }
        
        # Should match due to normalization
        assert album_match(tidal_album, spotify_album, config_with_fuzzy)
    
    def test_album_substring_match(self, config_with_fuzzy):
        """Test that album substring matching works"""
        tidal_album = MockTidalAlbum("The Wall", ["Pink Floyd"])
        spotify_album = {
            "name": "The Wall - Remastered",
            "artists": [{"name": "Pink Floyd"}]
        }
        
        # Should match even without fuzzy due to substring logic
        assert album_match(tidal_album, spotify_album, config_with_fuzzy)


class TestAlbumCaching:
    """Test album match caching functionality"""
    
    def setup_method(self):
        """Reset the album cache before each test"""
        album_match_cache.data = {}
    
    def test_populate_album_cache_basic(self):
        """Test basic album cache population"""
        config = {'enable_fuzzy_matching': False}
        
        spotify_albums = [
            {"id": "spotify_1", "name": "OK Computer", "artists": [{"name": "Radiohead"}]}
        ]
        
        tidal_albums = [
            MockTidalAlbum("OK Computer", ["Radiohead"], "tidal_1")
        ]
        
        populate_album_match_cache(spotify_albums, tidal_albums, config)
        
        # Should have cached the match
        assert album_match_cache.get("spotify_1") == "tidal_1"
    
    def test_populate_album_cache_no_match(self):
        """Test cache population when no matches exist"""
        config = {'enable_fuzzy_matching': False}
        
        spotify_albums = [
            {"id": "spotify_1", "name": "OK Computer", "artists": [{"name": "Radiohead"}]}
        ]
        
        tidal_albums = [
            MockTidalAlbum("Different Album", ["Different Artist"], "tidal_1")
        ]
        
        populate_album_match_cache(spotify_albums, tidal_albums, config)
        
        # Should not have cached any matches
        assert album_match_cache.get("spotify_1") is None
    
    def test_populate_album_cache_multiple_albums(self):
        """Test cache population with multiple albums"""
        config = {'enable_fuzzy_matching': False}
        
        spotify_albums = [
            {"id": "spotify_1", "name": "OK Computer", "artists": [{"name": "Radiohead"}]},
            {"id": "spotify_2", "name": "The Bends", "artists": [{"name": "Radiohead"}]}
        ]
        
        tidal_albums = [
            MockTidalAlbum("OK Computer", ["Radiohead"], "tidal_1"),
            MockTidalAlbum("The Bends", ["Radiohead"], "tidal_2")
        ]
        
        populate_album_match_cache(spotify_albums, tidal_albums, config)
        
        # Should have cached both matches
        assert album_match_cache.get("spotify_1") == "tidal_1"
        assert album_match_cache.get("spotify_2") == "tidal_2"
    
    def test_populate_album_cache_fuzzy_matching(self):
        """Test cache population with fuzzy matching enabled"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80
        }
        
        spotify_albums = [
            {"id": "spotify_1", "name": "OK Computer", "artists": [{"name": "Radiohead"}]}
        ]
        
        tidal_albums = [
            MockTidalAlbum("OK Computer (Collector's Edition)", ["Radiohead"], "tidal_1")
        ]
        
        populate_album_match_cache(spotify_albums, tidal_albums, config)
        
        # Should have cached the fuzzy match
        assert album_match_cache.get("spotify_1") == "tidal_1"


class TestAlbumSyncIntegration:
    """Integration tests for album sync components"""
    
    def setup_method(self):
        """Reset the album cache before each test"""
        album_match_cache.data = {}
    
    def test_album_cache_insert_and_retrieve(self):
        """Test basic album cache insert and retrieve operations"""
        album_match_cache.insert(("spotify_test", "tidal_test"))
        
        assert album_match_cache.get("spotify_test") == "tidal_test"
        assert album_match_cache.get("nonexistent") is None
    
    def test_album_match_with_multiple_artists(self):
        """Test album matching with multiple artists"""
        config = {'enable_fuzzy_matching': True, 'fuzzy_artist_threshold': 0.75}
        
        tidal_album = MockTidalAlbum("Collaboration Album", ["Artist One", "Artist Two"])
        spotify_album = {
            "name": "Collaboration Album",
            "artists": [{"name": "Artist One"}, {"name": "Artist Two"}]
        }
        
        assert album_match(tidal_album, spotify_album, config)
    
    def test_album_match_partial_artist_overlap(self):
        """Test album matching with partial artist overlap"""
        config = {'enable_fuzzy_matching': True, 'fuzzy_artist_threshold': 0.75}
        
        tidal_album = MockTidalAlbum("Various Artists Album", ["Artist One", "Artist Two"])
        spotify_album = {
            "name": "Various Artists Album",
            "artists": [{"name": "Artist One"}]  # Only one of the artists
        }
        
        # Should match if at least one artist overlaps
        assert album_match(tidal_album, spotify_album, config)
    
    def test_smashing_pumpkins_case(self):
        """Test the specific Smashing Pumpkins case that was failing"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80,
            'fuzzy_artist_threshold': 0.75
        }
        
        tidal_album = MockTidalAlbum("Mellon Collie and the Infinite Sadness", ["Smashing Pumpkins"])
        spotify_album = {
            "name": "Mellon Collie And The Infinite Sadness (Deluxe Edition)",
            "artists": [{"name": "The Smashing Pumpkins"}]
        }
        
        # Should match with fuzzy matching despite "The" prefix and case differences
        assert album_match(tidal_album, spotify_album, config)
    
    def test_artist_fuzzy_matching_with_the_prefix(self):
        """Test fuzzy artist matching when 'The' prefix is different"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_artist_threshold': 0.75
        }
        
        tidal_album = MockTidalAlbum("Test Album", ["Beatles"])
        spotify_album = {
            "name": "Test Album",
            "artists": [{"name": "The Beatles"}]
        }
        
        # Should match with fuzzy artist matching
        assert album_match(tidal_album, spotify_album, config)
    
    def test_run_dmc_case(self):
        """Test the specific Run-DMC case with special characters"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80,
            'fuzzy_artist_threshold': 0.75
        }
        
        # Test with en-dash vs regular hyphen
        tidal_album = MockTidalAlbum("RUN-DMC", ["Run-D.M.C."])
        spotify_album = {
            "name": "RUN-DMC (Expanded Edition)",
            "artists": [{"name": "Run–D.M.C."}]  # Note: en-dash in Spotify
        }
        
        # Should match with fuzzy matching despite en-dash vs hyphen difference
        assert album_match(tidal_album, spotify_album, config)
        
        # Test with simplified vs full punctuation
        tidal_album2 = MockTidalAlbum("RUN-DMC", ["Run-DMC"])
        assert album_match(tidal_album2, spotify_album, config)
    
    def test_stephen_malkmus_case(self):
        """Test the specific Stephen Malkmus case with & in artist name"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80,
            'fuzzy_artist_threshold': 0.75
        }
        
        # Test exact match with &
        tidal_album = MockTidalAlbum("Wig Out at Jagbags", ["Stephen Malkmus & The Jicks"])
        spotify_album = {
            "name": "Wig Out at Jagbags",
            "artists": [{"name": "Stephen Malkmus & The Jicks"}]
        }
        
        assert album_match(tidal_album, spotify_album, config)
        
        # Test when Tidal only has the main artist (common case)
        tidal_album_main_artist = MockTidalAlbum("Wig Out at Jagbags", ["Stephen Malkmus"])
        assert album_match(tidal_album_main_artist, spotify_album, config)
    
    def test_king_gizzard_case(self):
        """Test the specific King Gizzard case with apostrophe and & vs 'and'"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80,
            'fuzzy_artist_threshold': 0.75
        }
        
        spotify_album = {
            "name": "I'm In Your Mind Fuzz",
            "artists": [{"name": "King Gizzard & The Lizard Wizard"}]
        }
        
        # Test exact match with apostrophe and &
        tidal_album1 = MockTidalAlbum("I'm In Your Mind Fuzz", ["King Gizzard & The Lizard Wizard"])
        assert album_match(tidal_album1, spotify_album, config)
        
        # Test without apostrophe
        tidal_album2 = MockTidalAlbum("Im In Your Mind Fuzz", ["King Gizzard & The Lizard Wizard"])
        assert album_match(tidal_album2, spotify_album, config)
        
        # Test with "and" instead of "&"
        tidal_album3 = MockTidalAlbum("I'm In Your Mind Fuzz", ["King Gizzard and The Lizard Wizard"])
        assert album_match(tidal_album3, spotify_album, config)
        
        # Test with shortened artist name
        tidal_album4 = MockTidalAlbum("I'm In Your Mind Fuzz", ["King Gizzard"])
        assert album_match(tidal_album4, spotify_album, config)
    
    def test_ichiko_aoba_case(self):
        """Test the specific Ichiko Aoba case that was failing in search"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80,
            'fuzzy_artist_threshold': 0.75
        }
        
        spotify_album = {
            "name": "Asleep Among Endives",
            "artists": [{"name": "Ichiko Aoba"}]
        }
        
        # Test exact match
        tidal_album1 = MockTidalAlbum("Asleep Among Endives", ["Ichiko Aoba"])
        assert album_match(tidal_album1, spotify_album, config)
        
        # Test with different casing
        tidal_album2 = MockTidalAlbum("asleep among endives", ["ichiko aoba"])
        assert album_match(tidal_album2, spotify_album, config)
        
        # Test with partial match (album name shortened)
        tidal_album3 = MockTidalAlbum("Asleep Among Endives", ["Ichiko Aoba"])
        assert album_match(tidal_album3, spotify_album, config)
    
    def test_comprehensive_matching_cases(self):
        """Comprehensive test covering all the album matching edge cases we've encountered"""
        config = {
            'enable_fuzzy_matching': True,
            'fuzzy_name_threshold': 0.80,
            'fuzzy_artist_threshold': 0.75
        }
        
        test_cases = [
            # Case 1: Nirvana Bleach - colon vs parentheses punctuation
            {
                'description': 'Nirvana Bleach : vs ( ) punctuation',
                'spotify': {"name": "Bleach: Deluxe Edition", "artists": [{"name": "Nirvana"}]},
                'tidal_variants': [
                    ("Bleach (Deluxe Edition)", ["Nirvana"], True),  # Should match
                    ("Bleach: Deluxe Edition", ["Nirvana"], True),   # Exact match
                ]
            },
            
            # Case 2: Smashing Pumpkins - "The" prefix handling
            {
                'description': 'Smashing Pumpkins "The" prefix',
                'spotify': {"name": "Mellon Collie And The Infinite Sadness (Deluxe Edition)", "artists": [{"name": "The Smashing Pumpkins"}]},
                'tidal_variants': [
                    ("Mellon Collie and the Infinite Sadness", ["Smashing Pumpkins"], True),  # Should match
                    ("Mellon Collie And The Infinite Sadness (Deluxe Edition)", ["The Smashing Pumpkins"], True),  # Exact
                ]
            },
            
            # Case 3: Run-DMC - en-dash vs hyphen and punctuation variations
            {
                'description': 'Run-DMC dash and punctuation variations',
                'spotify': {"name": "RUN-DMC (Expanded Edition)", "artists": [{"name": "Run–D.M.C."}]},  # en-dash
                'tidal_variants': [
                    ("RUN-DMC", ["Run-D.M.C."], True),    # Should match with fuzzy
                    ("RUN-DMC", ["Run-DMC"], True),       # Should match with fuzzy
                    ("RUN-DMC (Expanded Edition)", ["Run–D.M.C."], True),  # Exact
                ]
            },
            
            # Case 4: Stephen Malkmus - & vs "and" in artist names
            {
                'description': 'Stephen Malkmus & vs "and"',
                'spotify': {"name": "Wig Out at Jagbags", "artists": [{"name": "Stephen Malkmus & The Jicks"}]},
                'tidal_variants': [
                    ("Wig Out at Jagbags", ["Stephen Malkmus & The Jicks"], True),  # Exact
                    ("Wig Out at Jagbags", ["Stephen Malkmus and The Jicks"], True),  # "and" vs "&"
                    ("Wig Out at Jagbags", ["Stephen Malkmus"], True),  # Main artist only
                ]
            },
            
            # Case 5: King Gizzard - apostrophe and & vs "and"
            {
                'description': 'King Gizzard apostrophe and & vs "and"',
                'spotify': {"name": "I'm In Your Mind Fuzz", "artists": [{"name": "King Gizzard & The Lizard Wizard"}]},
                'tidal_variants': [
                    ("I'm In Your Mind Fuzz", ["King Gizzard & The Lizard Wizard"], True),  # Exact
                    ("Im In Your Mind Fuzz", ["King Gizzard & The Lizard Wizard"], True),   # No apostrophe
                    ("I'm In Your Mind Fuzz", ["King Gizzard and The Lizard Wizard"], True), # "and" vs "&"
                    ("I'm In Your Mind Fuzz", ["King Gizzard"], True),  # Shortened artist
                ]
            },
            
            # Case 6: Ichiko Aoba - exact match (would fail in search but should match if found)
            {
                'description': 'Ichiko Aoba exact case',
                'spotify': {"name": "Asleep Among Endives", "artists": [{"name": "Ichiko Aoba"}]},
                'tidal_variants': [
                    ("Asleep Among Endives", ["Ichiko Aoba"], True),  # Exact
                    ("asleep among endives", ["ichiko aoba"], True),  # Case insensitive
                ]
            },
            
            # Case 7: Fuzzy matching threshold tests
            {
                'description': 'Fuzzy matching edge cases',
                'spotify': {"name": "OK Computer", "artists": [{"name": "Radiohead"}]},
                'tidal_variants': [
                    ("OK Komputer", ["Radiohead"], True),   # Should match with fuzzy (0.909 > 0.80)
                    ("Computer OK", ["Radiohead"], False),  # Should NOT match (0.727 < 0.80)
                    ("The OK Computer", ["Radiohead"], True), # Should match (substring)
                ]
            },
        ]
        
        for test_case in test_cases:
            spotify_album = test_case['spotify']
            print(f"\\nTesting: {test_case['description']}")
            
            for tidal_name, tidal_artists, should_match in test_case['tidal_variants']:
                tidal_album = MockTidalAlbum(tidal_name, tidal_artists)
                result = album_match(tidal_album, spotify_album, config)
                
                print(f"  '{spotify_album['name']}' by {[a['name'] for a in spotify_album['artists']]} vs")
                print(f"  '{tidal_name}' by {tidal_artists} -> {'✓' if result else '✗'}")
                
                assert result == should_match, f"Expected {should_match}, got {result} for {tidal_name} by {tidal_artists}"