#!/usr/bin/env python3
"""
Test script to selectively clear saved albums, playlists, favorites, and followed artists from Tidal account.

WARNING: This will permanently delete data from your Tidal account!
Use this only for testing purposes on a test account.

This script integrates with the spotify_to_tidal configuration system:
- Uses the same Tidal authentication flow as the main application
- Loads config.yml (or custom config file) for consistency
- Reuses existing .session.yml file for Tidal authentication
- Does not require Spotify credentials since it only touches Tidal

Usage:
    ./clear_tidal_account.py                                          # Clear everything
    ./clear_tidal_account.py --config test.yml                       # Use custom config file
    ./clear_tidal_account.py --clear-favorites                       # Clear only favorites
    ./clear_tidal_account.py --clear-albums --clear-artists          # Clear albums and artists
    ./clear_tidal_account.py --no-clear-playlists                    # Clear everything except playlists

Available clear options:
- --clear-favorites / --no-clear-favorites: Clear favorite tracks
- --clear-albums / --no-clear-albums: Clear saved albums  
- --clear-playlists / --no-clear-playlists: Clear user-created playlists
- --clear-artists / --no-clear-artists: Clear followed artists

The script will:
1. Load the config file (optional, mainly for consistency)
2. Authenticate with Tidal using existing session or OAuth flow
3. Selectively clear the specified data types from your Tidal account

Multiple confirmation prompts ensure you don't accidentally delete data.
"""

import asyncio
import sys
import yaml
import argparse
from pathlib import Path

# Add the src directory to the path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from spotify_to_tidal.auth import open_tidal_session
from spotify_to_tidal.tidalapi_patch import get_all_favorites, get_all_playlists, get_all_saved_albums, get_all_saved_artists
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


async def clear_followed_artists(session: tidalapi.Session):
    """Clear all followed artists"""
    print("Fetching all followed artists...")
    artists = await get_all_saved_artists(session.user)
    
    if not artists:
        print("No followed artists to clear.")
        return
    
    print(f"Found {len(artists)} followed artists. Clearing...")
    
    # Remove artists in chunks
    chunk_size = 20
    with tqdm(desc="Unfollowing artists", total=len(artists)) as progress:
        for i in range(0, len(artists), chunk_size):
            chunk = artists[i:i + chunk_size]
            
            for artist in chunk:
                try:
                    session.user.favorites.remove_artist(artist.id)
                except Exception as e:
                    print(f"Error unfollowing artist {artist.id} ({artist.name}): {e}")
            
            progress.update(len(chunk))
    
    print("✓ All followed artists cleared.")


async def main():
    """Main function to clear all Tidal account data"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Clear data from Tidal account")
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--clear-favorites', action=argparse.BooleanOptionalAction, help='clear favorite tracks')
    parser.add_argument('--clear-albums', action=argparse.BooleanOptionalAction, help='clear saved albums')
    parser.add_argument('--clear-playlists', action=argparse.BooleanOptionalAction, help='clear user-created playlists')
    parser.add_argument('--clear-artists', action=argparse.BooleanOptionalAction, help='clear followed artists')
    args = parser.parse_args()
    
    # Determine what to clear based on arguments
    # If no clear options are specified via CLI args, default to clearing everything
    any_clear_args_specified = any([
        args.clear_favorites is not None,
        args.clear_albums is not None,
        args.clear_playlists is not None,
        args.clear_artists is not None
    ])
    
    if any_clear_args_specified:
        # Explicit args provided - only clear what's explicitly enabled
        clear_favorites_flag = args.clear_favorites if args.clear_favorites is not None else False
        clear_albums_flag = args.clear_albums if args.clear_albums is not None else False
        clear_playlists_flag = args.clear_playlists if args.clear_playlists is not None else False
        clear_artists_flag = args.clear_artists if args.clear_artists is not None else False
    else:
        # No explicit args - clear everything
        clear_favorites_flag = True
        clear_albums_flag = True
        clear_playlists_flag = True
        clear_artists_flag = True
    
    # Build warning message based on what will be cleared
    items_to_clear = []
    if clear_favorites_flag:
        items_to_clear.append("All favorite tracks")
    if clear_albums_flag:
        items_to_clear.append("All saved albums")
    if clear_playlists_flag:
        items_to_clear.append("All user-created playlists")
    if clear_artists_flag:
        items_to_clear.append("All followed artists")
    
    if not items_to_clear:
        print("No items selected for clearing. Use --help to see available options.")
        return 0
    
    print("🚨 WARNING: This script will permanently delete the following from your Tidal account:")
    for item in items_to_clear:
        print(f"   - {item}")
    print("\nThis action CANNOT be undone!")
    
    confirmation_text = "DELETE ALL" if len(items_to_clear) > 1 else "DELETE"
    response = input(f"\nAre you absolutely sure you want to proceed? (type '{confirmation_text}' to confirm): ")
    if response != confirmation_text:
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
        
        # Clear selected items
        cleared_items = []
        
        if clear_favorites_flag:
            print("\n" + "="*50)
            await clear_favorites(session)
            cleared_items.append("favorites")
        
        if clear_albums_flag:
            print("\n" + "="*50)
            await clear_saved_albums(session)
            cleared_items.append("saved albums")
        
        if clear_playlists_flag:
            print("\n" + "="*50)
            await clear_user_playlists(session)
            cleared_items.append("user playlists")
            
        if clear_artists_flag:
            print("\n" + "="*50)
            await clear_followed_artists(session)
            cleared_items.append("followed artists")
        
        print("\n" + "="*50)
        print("🎉 Selected Tidal data successfully cleared!")
        if cleared_items:
            print(f"Cleared: {', '.join(cleared_items)}")
        else:
            print("No items were cleared.")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)