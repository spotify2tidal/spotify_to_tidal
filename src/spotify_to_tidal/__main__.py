import yaml
import argparse
import sys

from . import sync as _sync
from . import auth as _auth

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--uri', help='synchronize a specific URI instead of the one in the config')
    parser.add_argument('--sync-favorites', action=argparse.BooleanOptionalAction, help='synchronize the favorites')
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    print("Opening Spotify session")
    spotify_session = _auth.open_spotify_session(config['spotify'])
    print("Opening Tidal session")
    tidal_session = _auth.open_tidal_session()
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")
    sync_favorites = args.sync_favorites or config.get('sync_favorites_default', False)
    if args.uri:
        # if a playlist ID is explicitly provided as a command line argument then use that
        spotify_playlist = spotify_session.playlist(args.uri)
        tidal_playlists = _sync.get_tidal_playlists_wrapper(tidal_session)
        tidal_playlist = _sync.pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists)
        _sync.sync_playlists_wrapper(spotify_session, tidal_session, [tidal_playlist], config, to='spotify')
    elif args.sync_favorites:
        sync_favorites = True # sync only the favorites
    elif entries:=config.get('sync_playlists', None):
        if isinstance(entries, list):
            # if the config contains a sync_playlists list of mappings then use that
            playlist_map =  _sync.get_playlists_from_config(spotify_session, tidal_session, entries)
            _sync.sync_playlists_wrapper(spotify_session, tidal_session, playlist_map, config, to='tidal')
        # should be a list
        elif isinstance(entries, dict):
            if x:= entries.get('tidal'):
                playlist_map_tidal = _sync.get_playlists_from_config(spotify_session, tidal_session, x)
                print("Syncing playlists from spotify to tidal.")
            _sync.sync_playlists_wrapper(spotify_session, tidal_session, playlist_map_tidal, config, to='tidal')
            if y:= entries.get('spotify'):
                playlist_map_spotify = _sync.get_playlists_from_config(spotify_session, tidal_session, y)
                print("Syncing playlists from tidal to spotify.")
                _sync.sync_playlists_wrapper(spotify_session, tidal_session, playlist_map_spotify, config, to='spotify')
                

    else:
        # otherwise sync all the user playlists in the Spotify account and favorites unless explicitly disabled
        _sync.sync_playlists_wrapper(spotify_session, tidal_session, _sync.get_user_playlist_mappings(spotify_session, tidal_session, config), config, to='tidal')

    if sync_favorites:
        _sync.sync_favorites_wrapper(spotify_session, tidal_session, config)

if __name__ == '__main__':
    main()
    sys.exit(0)
