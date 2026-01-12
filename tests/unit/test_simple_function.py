# tests/unit/test_simple_function.py

import pytest
import sys
from pathlib import Path

# Add the src directory to the path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from spotify_to_tidal.sync import simple


class TestSimpleFunction:
    """Test the simple() text normalization function"""
    
    def test_empty_string(self):
        """Test empty string input returns [""]"""
        assert simple("") == [""]
        assert simple("   ") == [""]  # whitespace only should be treated as empty
    
    def test_simple_strings_without_parentheses(self):
        """Test simple strings without parentheses return single-item list"""
        assert simple("OK Computer") == ["OK Computer"]
        assert simple("The Beatles") == ["The Beatles"]
        assert simple("Dark Side of the Moon") == ["Dark Side of the Moon"]
    
    def test_strings_with_parentheses(self):
        """Test strings with parentheses return both exact and simplified versions"""
        assert simple("OK Computer (Deluxe Edition)") == ["OK Computer (Deluxe Edition)", "OK Computer"]
        assert simple("The Wall (Remastered)") == ["The Wall (Remastered)", "The Wall"]
        assert simple("Album Title (Special Edition) (Bonus Tracks)") == ["Album Title (Special Edition) (Bonus Tracks)", "Album Title"]
    
    def test_strings_with_brackets(self):
        """Test strings with square brackets return both exact and simplified versions"""
        assert simple("OK Computer [Deluxe Edition]") == ["OK Computer [Deluxe Edition]", "OK Computer"]
        assert simple("The Wall [Remastered]") == ["The Wall [Remastered]", "The Wall"]
        assert simple("Album [Special Edition] [Bonus]") == ["Album [Special Edition] [Bonus]", "Album"]
    
    def test_mixed_brackets_and_parentheses(self):
        """Test strings with both brackets and parentheses"""
        assert simple("Album Title [Deluxe] (Remastered)") == ["Album Title [Deluxe] (Remastered)", "Album Title"]
        assert simple("Song (Radio Edit) [Single]") == ["Song (Radio Edit) [Single]", "Song"]
    
    def test_dash_normalization(self):
        """Test that different dash types are normalized to regular hyphens"""
        # en-dash (–)
        assert simple("Test–Album") == ["Test-Album"]
        # em-dash (—) 
        assert simple("Test—Album") == ["Test-Album"]
        # minus sign (−)
        assert simple("Test−Album") == ["Test-Album"]
        # multiple different dashes
        assert simple("Test–Album—Song−Mix") == ["Test-Album-Song-Mix"]
    
    def test_dash_normalization_with_parentheses(self):
        """Test dash normalization works with parentheses removal"""
        assert simple("Test–Album (Deluxe Edition)") == ["Test-Album (Deluxe Edition)", "Test-Album"]
        assert simple("Artist—Album (Remastered)") == ["Artist-Album (Remastered)", "Artist-Album"]
    
    def test_whitespace_normalization(self):
        """Test that multiple whitespace is normalized to single spaces"""
        assert simple("OK  Computer") == ["OK Computer"]
        assert simple("  OK   Computer  ") == ["OK Computer"]
        assert simple("OK\tComputer\nAlbum") == ["OK Computer Album"]
    
    def test_whitespace_with_parentheses(self):
        """Test whitespace normalization with parentheses"""
        assert simple("OK  Computer  (Deluxe  Edition)") == ["OK Computer (Deluxe Edition)", "OK Computer"]
        assert simple("  Album   Title  (  Special  )  ") == ["Album Title ( Special )", "Album Title"]
    
    def test_duplicate_detection(self):
        """Test that when exact equals simplified, only one version is returned"""
        # No parentheses means exact == simplified
        assert simple("Simple Album") == ["Simple Album"]
        # Empty parentheses should result in duplicate
        assert simple("Album ()") == ["Album ()", "Album"]
        # Whitespace-only in parentheses
        assert simple("Album (   )") == ["Album ( )", "Album"]
    
    def test_edge_cases(self):
        """Test various edge cases"""
        # Only parentheses
        assert simple("(Deluxe Edition)") == ["(Deluxe Edition)", ""]
        # Only brackets
        assert simple("[Remastered]") == ["[Remastered]", ""]
        # Parentheses at the beginning 
        assert simple("(Special) Album Title") == ["(Special) Album Title", ""]
        # Multiple parentheses groups
        assert simple("Album (Part 1) Title (Part 2)") == ["Album (Part 1) Title (Part 2)", "Album"]
    
    def test_real_world_examples(self):
        """Test with real-world album/track names that have caused issues"""
        # Smashing Pumpkins case
        assert simple("Mellon Collie And The Infinite Sadness (Deluxe Edition)") == [
            "Mellon Collie And The Infinite Sadness (Deluxe Edition)", 
            "Mellon Collie And The Infinite Sadness"
        ]
        
        # Run-DMC with en-dash
        assert simple("RUN–DMC (Expanded Edition)") == [
            "RUN-DMC (Expanded Edition)",
            "RUN-DMC"
        ]
        
        # King Gizzard with apostrophe
        assert simple("I'm In Your Mind Fuzz") == ["I'm In Your Mind Fuzz"]
        
        # Nirvana with colon
        assert simple("Bleach: Deluxe Edition") == ["Bleach: Deluxe Edition"]
        
        # Multiple format indicators
        assert simple("Album Title (Deluxe) (Remastered) (Bonus Tracks)") == [
            "Album Title (Deluxe) (Remastered) (Bonus Tracks)",
            "Album Title"
        ]
    
    def test_unicode_normalization(self):
        """Test that unicode characters are preserved"""
        assert simple("Ágætis byrjun") == ["Ágætis byrjun"]
        assert simple("Ágætis byrjun (Deluxe)") == ["Ágætis byrjun (Deluxe)", "Ágætis byrjun"]
        assert simple("Sigur Rós") == ["Sigur Rós"]
    
    def test_special_punctuation_preservation(self):
        """Test that other special punctuation is preserved"""
        # Colons, periods, apostrophes should be preserved
        assert simple("OK Computer: OKNOTOK 1997 2017") == ["OK Computer: OKNOTOK 1997 2017"]
        assert simple("Don't Look Back") == ["Don't Look Back"]
        assert simple("U.S.A.") == ["U.S.A."]
        assert simple("Ph.D.") == ["Ph.D."]
    
    def test_function_return_type(self):
        """Test that the function always returns a list"""
        result = simple("Test")
        assert isinstance(result, list)
        assert len(result) >= 1  # Should always return at least one item
        
        result = simple("Test (Deluxe)")
        assert isinstance(result, list)
        assert len(result) == 2  # Should return exactly two items when different