import yaml
import argparse
import sys

from . import sync as _sync
from . import auth as _auth

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--uri', help='synchronize a specific URI instead of the one in the config')
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    print("Opening Spotify session")
    spotify_session = _auth.open_spotify_session(config['spotify'])
    print("Opening Tidal session")
    tidal_session = _auth.open_tidal_session()
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")
    if args.uri:
        # if a playlist ID is explicitly provided as a command line argument then use that
        spotify_playlist = spotify_session.playlist(args.uri)
        tidal_playlists = _sync.get_tidal_playlists_dict(tidal_session)
        tidal_playlist = _sync.pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists)
        _sync.sync_list(spotify_session, tidal_session, [tidal_playlist], config)
    elif config.get('sync_playlists', None):
        # if the config contains a sync_playlists list of mappings then use that
        _sync.sync_list(spotify_session, tidal_session, _sync.get_playlists_from_config(spotify_session, tidal_session, config), config)
    else:
        # otherwise just use the user playlists in the Spotify account
        _sync.sync_list(spotify_session, tidal_session, _sync.get_user_playlist_mappings(spotify_session, tidal_session, config), config)

if __name__ == '__main__':
    main()
    sys.exit(0)
