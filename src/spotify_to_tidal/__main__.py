import yaml
import argparse
import sys

from . import sync as _sync
from . import auth as _auth
from . import logfile as _logfile

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--uri', help='synchronize a specific URI instead of the one in the config')
    parser.add_argument('--sync-playlists', action=argparse.BooleanOptionalAction, help='synchronize the playlists')
    parser.add_argument('--sync-favorites', action=argparse.BooleanOptionalAction, help='synchronize the favorites')
    parser.add_argument('--sync-albums', action=argparse.BooleanOptionalAction, help='synchronize saved albums')
    parser.add_argument('--sync-artists', action=argparse.BooleanOptionalAction, help='synchronize followed artists')
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Determine what to sync based on arguments and config
    # If no sync options are specified via CLI args, default to syncing everything
    # unless config defaults override this behavior
    any_sync_args_specified = any([
        args.sync_playlists is not None,
        args.sync_favorites is not None, 
        args.sync_albums is not None,
        args.sync_artists is not None
    ])
    
    if any_sync_args_specified:
        # Explicit args provided - only sync what's explicitly enabled
        sync_playlists = args.sync_playlists if args.sync_playlists is not None else False
        sync_favorites = args.sync_favorites if args.sync_favorites is not None else False
        sync_albums = args.sync_albums if args.sync_albums is not None else False
        sync_artists = args.sync_artists if args.sync_artists is not None else False
    else:
        # No explicit args - use config defaults, but default to True if config doesn't specify
        sync_playlists = config.get('sync_playlists_default', True)
        sync_favorites = config.get('sync_favorites_default', True) 
        sync_albums = config.get('sync_albums_default', True)
        sync_artists = config.get('sync_artists_default', True)
    
    print("Opening Spotify session")
    spotify_session = _auth.open_spotify_session(config['spotify'])
    print("Opening Tidal session")
    tidal_session = _auth.open_tidal_session()
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")
    
    # Clear any previous not found logs
    _logfile.clear_not_found_log()

    # Prepare the followed-artist sync FIRST (when enabled): this builds the set of artists that still
    # need following on Tidal. We run it before the track/album syncs as an optimisation - since most
    # followed artists also have a track or album somewhere in the collection, matching those releases
    artist_ctx = None
    if sync_artists:
        artist_ctx = _sync.prepare_artist_sync_wrapper(spotify_session, tidal_session, config)

    if sync_playlists:
        if args.uri:
            # if a playlist ID is explicitly provided as a command line argument then use that
            spotify_playlist = spotify_session.playlist(args.uri)
            tidal_playlists = _sync.get_tidal_playlists_wrapper(tidal_session)
            playlist_mapping = _sync.pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists)
            _sync.sync_playlists_wrapper(spotify_session, tidal_session, [playlist_mapping], config)
        elif config.get('sync_playlists', None):
            # if the config contains a sync_playlists list of mappings then use that
            _sync.sync_playlists_wrapper(spotify_session, tidal_session, _sync.get_playlists_from_config(spotify_session, tidal_session, config), config)
        else:
            # otherwise sync all the user playlists in the Spotify account
            _sync.sync_playlists_wrapper(spotify_session, tidal_session, _sync.get_user_playlist_mappings(spotify_session, tidal_session, config), config)

    if sync_favorites:
        _sync.sync_favorites_wrapper(spotify_session, tidal_session, config)

    if sync_albums:
        _sync.sync_albums_wrapper(spotify_session, tidal_session, config)

    if sync_artists:
        _sync.finish_artist_sync_wrapper(spotify_session, tidal_session, config, *artist_ctx)

    # Write consolidated log of all items not found
    _logfile.write_not_found_log()

if __name__ == '__main__':
    main()
    sys.exit(0)
