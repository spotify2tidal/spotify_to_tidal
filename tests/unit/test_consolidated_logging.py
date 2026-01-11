# tests/unit/test_consolidated_logging.py

import sys
from pathlib import Path
import os

# Add the src directory to the path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from spotify_to_tidal.sync import add_not_found_item, write_not_found_log, clear_not_found_log


class TestConsolidatedLogging:
    """Test the consolidated not found logging functionality"""
    
    def test_add_and_clear_not_found_items(self):
        """Test adding items and clearing the list"""
        # Clear any existing items
        clear_not_found_log()
        
        # Add some items
        add_not_found_item('track', 'Artist - Song Name', 'Playlist 1')
        add_not_found_item('album', 'Artist - Album Name')
        add_not_found_item('artist', 'Artist Name')
        
        # Write the log file
        write_not_found_log()
        
        # Verify file was created
        assert os.path.exists("items not found.txt")
        
        # Read and verify content
        with open("items not found.txt", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Verify structure
        assert "Spotify to Tidal Sync Log" in content
        assert "Items Not Found on Tidal" in content
        assert "TRACKS/SONGS:" in content
        assert "ALBUMS:" in content
        assert "ARTISTS:" in content
        assert "Artist - Song Name (from Playlist 1)" in content
        assert "Artist - Album Name" in content
        assert "Artist Name" in content
        assert "Total items not found: 3" in content
        
        # Clear items
        clear_not_found_log()
        
        # Cleanup
        if os.path.exists("items not found.txt"):
            os.remove("items not found.txt")
    
    def test_no_items_creates_no_file(self):
        """Test that no file is created when no items are not found"""
        # Clear any existing items
        clear_not_found_log()
        
        # Ensure file doesn't exist
        if os.path.exists("items not found.txt"):
            os.remove("items not found.txt")
        
        # Write log with no items
        write_not_found_log()
        
        # Verify no file was created
        assert not os.path.exists("items not found.txt")
    
    def test_overwrite_not_append(self):
        """Test that the log file is overwritten, not appended to"""
        # Clear any existing items
        clear_not_found_log()
        
        # Add an item and write
        add_not_found_item('track', 'First Track', 'Playlist 1')
        write_not_found_log()
        
        # Verify file exists with first content
        with open("items not found.txt", "r", encoding="utf-8") as f:
            first_content = f.read()
        assert "First Track" in first_content
        assert "Total items not found: 1" in first_content
        
        # Clear and add different items
        clear_not_found_log()
        add_not_found_item('album', 'Second Album')
        add_not_found_item('artist', 'Second Artist')
        write_not_found_log()
        
        # Verify file was overwritten (not appended)
        with open("items not found.txt", "r", encoding="utf-8") as f:
            second_content = f.read()
        assert "First Track" not in second_content  # Old content should be gone
        assert "Second Album" in second_content
        assert "Second Artist" in second_content
        assert "Total items not found: 2" in second_content
        
        # Cleanup
        if os.path.exists("items not found.txt"):
            os.remove("items not found.txt")
    
    def test_grouping_by_type(self):
        """Test that items are properly grouped by type"""
        # Clear any existing items
        clear_not_found_log()
        
        # Add items in mixed order
        add_not_found_item('artist', 'Artist 1')
        add_not_found_item('track', 'Track 1', 'Playlist 1')
        add_not_found_item('album', 'Album 1')
        add_not_found_item('track', 'Track 2', 'Playlist 2')
        add_not_found_item('artist', 'Artist 2')
        
        write_not_found_log()
        
        # Read content
        with open("items not found.txt", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Verify sections exist and are in order
        lines = content.split('\n')
        
        # Find section headers
        tracks_idx = next(i for i, line in enumerate(lines) if line == "TRACKS/SONGS:")
        albums_idx = next(i for i, line in enumerate(lines) if line == "ALBUMS:")
        artists_idx = next(i for i, line in enumerate(lines) if line == "ARTISTS:")
        
        # Verify ordering: tracks first, then albums, then artists
        assert tracks_idx < albums_idx < artists_idx
        
        # Verify tracks section contains both tracks
        tracks_section = '\n'.join(lines[tracks_idx:albums_idx])
        assert "Track 1 (from Playlist 1)" in tracks_section
        assert "Track 2 (from Playlist 2)" in tracks_section
        
        # Verify total count
        assert "Total items not found: 5" in content
        
        # Cleanup
        clear_not_found_log()
        if os.path.exists("items not found.txt"):
            os.remove("items not found.txt")