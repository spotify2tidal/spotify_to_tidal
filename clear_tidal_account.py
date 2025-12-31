#!/usr/bin/env python3
"""
Test script to clear all saved albums, playlists, and favorites from Tidal account.

WARNING: This will permanently delete all your Tidal favorites, saved albums, and user-created playlists!
Use this only for testing purposes on a test account.

This script integrates with the spotify_to_tidal configuration system:
- Uses the same Tidal authentication flow as the main application
- Loads config.yml (or custom config file) for consistency
- Reuses existing .session.yml file for Tidal authentication
- Does not require Spotify credentials since it only touches Tidal

Usage:
    ./clear_tidal_account.py                    # Use default config.yml
    ./clear_tidal_account.py --config test.yml # Use custom config file

The script will:
1. Load the config file (optional, mainly for consistency)
2. Authenticate with Tidal using existing session or OAuth flow
3. Clear all favorite tracks from your Tidal library
4. Clear all saved albums from your Tidal collection
5. Delete all user-created playlists (not system playlists like "My Mix")

Multiple confirmation prompts ensure you don't accidentally delete everything.
"""

import asyncio
import sys
import yaml
import argparse
from pathlib import Path

# Add the src directory to the path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from spotify_to_tidal.auth import open_tidal_session
from spotify_to_tidal.tidalapi_patch import get_all_favorites, get_all_playlists, get_all_saved_albums
import tidalapi
from tqdm import tqdm


async def clear_favorites(session: tidalapi.Session):
    """Clear all favorite tracks"""
    print("Fetching all favorite tracks...")
    favorites = await get_all_favorites(session.user.favorites)
    
    if not favorites:
        print("No favorite tracks to clear.")
        return
    
    print(f"Found {len(favorites)} favorite tracks. Clearing...")
    
    # Remove favorites in chunks to avoid API rate limits
    chunk_size = 20
    with tqdm(desc="Removing favorite tracks", total=len(favorites)) as progress:
        for i in range(0, len(favorites), chunk_size):
            chunk = favorites[i:i + chunk_size]
            track_ids = [track.id for track in chunk]
            
            # Remove tracks from favorites
            for track_id in track_ids:
                try:
                    session.user.favorites.remove_track(track_id)
                except Exception as e:
                    print(f"Error removing track {track_id}: {e}")
            
            progress.update(len(chunk))
    
    print("✓ All favorite tracks cleared.")


async def clear_saved_albums(session: tidalapi.Session):
    """Clear all saved albums"""
    print("Fetching all saved albums...")
    albums = await get_all_saved_albums(session.user)
    
    if not albums:
        print("No saved albums to clear.")
        return
    
    print(f"Found {len(albums)} saved albums. Clearing...")
    
    # Remove albums in chunks
    chunk_size = 20
    with tqdm(desc="Removing saved albums", total=len(albums)) as progress:
        for i in range(0, len(albums), chunk_size):
            chunk = albums[i:i + chunk_size]
            
            for album in chunk:
                try:
                    session.user.favorites.remove_album(album.id)
                except Exception as e:
                    print(f"Error removing album {album.id} ({album.name}): {e}")
            
            progress.update(len(chunk))
    
    print("✓ All saved albums cleared.")


async def clear_user_playlists(session: tidalapi.Session):
    """Clear all user-created playlists (not system playlists)"""
    print("Fetching all playlists...")
    playlists = await get_all_playlists(session.user)
    
    # Filter to only user-created playlists (not system ones like "My Mix")
    user_playlists = [p for p in playlists if isinstance(p, tidalapi.UserPlaylist) and p.creator.id == session.user.id]
    
    if not user_playlists:
        print("No user-created playlists to clear.")
        return
    
    print(f"Found {len(user_playlists)} user-created playlists:")
    for playlist in user_playlists:
        print(f"  - {playlist.name} ({playlist.num_tracks} tracks)")
    
    # Ask for confirmation since this is destructive
    response = input(f"\nAre you sure you want to DELETE all {len(user_playlists)} user playlists? (yes/no): ")
    if response.lower() != 'yes':
        print("Playlist deletion cancelled.")
        return
    
    print("Deleting playlists...")
    with tqdm(desc="Deleting playlists", total=len(user_playlists)) as progress:
        for playlist in user_playlists:
            try:
                playlist.delete()
                print(f"✓ Deleted playlist: {playlist.name}")
            except Exception as e:
                print(f"✗ Error deleting playlist {playlist.name}: {e}")
            
            progress.update(1)
    
    print("✓ All user playlists cleared.")


async def main():
    """Main function to clear all Tidal account data"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Clear all data from Tidal account")
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    args = parser.parse_args()
    
    print("🚨 WARNING: This script will permanently delete ALL of the following from your Tidal account:")
    print("   - All favorite tracks")
    print("   - All saved albums") 
    print("   - All user-created playlists")
    print("\nThis action CANNOT be undone!")
    
    response = input("\nAre you absolutely sure you want to proceed? (type 'DELETE' to confirm): ")
    if response != 'DELETE':
        print("Operation cancelled. Your Tidal account is unchanged.")
        return
    
    try:
        # Load config if available (mainly for consistency with main app)
        try:
            with open(args.config, 'r') as f:
                config = yaml.safe_load(f)
                print(f"✓ Loaded config from {args.config}")
        except FileNotFoundError:
            print(f"Config file {args.config} not found, proceeding without it...")
            config = None
        except Exception as e:
            print(f"Warning: Could not load config: {e}")
            config = None
        
        # Get Tidal session (same way as main app)
        print("\nAuthenticating with Tidal...")
        session = open_tidal_session(config.get('tidal') if config else None)
        
        if not session.check_login():
            print("❌ Could not connect to Tidal")
            return 1
            
        print(f"✓ Authenticated as: {session.user.first_name} {session.user.last_name}")
        
        # Clear favorites
        print("\n" + "="*50)
        await clear_favorites(session)
        
        # Clear saved albums
        print("\n" + "="*50)
        await clear_saved_albums(session)
        
        # Clear user playlists
        print("\n" + "="*50)
        await clear_user_playlists(session)
        
        print("\n" + "="*50)
        print("🎉 Tidal account successfully cleared!")
        print("Your account now has no favorites, saved albums, or user playlists.")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)