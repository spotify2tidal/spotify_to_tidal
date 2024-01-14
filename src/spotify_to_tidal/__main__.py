import argparse
import logging
import sys
import yaml

from .auth import open_tidal_session, open_spotify_session
from .sync import sync_list
from .sync import get_tidal_playlists_dict, pick_tidal_playlist_for_spotify_playlist, get_playlists_from_config, get_user_playlist_mappings
from .type import SyncConfig

def main():
    log_map = [
        logging.WARNING,
        logging.INFO,
        logging.DEBUG
    ]
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--uri', help='synchronize a specific URI instead of the one in the config')
    parser.add_argument('-v', help='verbosity level, increases per v specified', default=0, action='count', dest='verbosity')
    args = parser.parse_args()

    logging.root = logging.basicConfig(level=log_map[min(args.verbosity, 3)], format='[%(asctime)s] %(levelname)s %(module)s:%(funcName)s:%(lineno)d - %(message)s', stream=sys.stderr)
    with open(args.config, 'r') as f:
        config: SyncConfig = yaml.safe_load(f)
    spotify_session = open_spotify_session(config['spotify'])

    tidal_session = open_tidal_session()
    if not tidal_session.check_login():
        logging.critical("Could not connect to Tidal")
        sys.exit(1)
    if args.uri:
        # if a playlist ID is explicitly provided as a command line argument then use that
        spotify_playlist = spotify_session.playlist(args.uri)
        tidal_playlists = get_tidal_playlists_dict(tidal_session)
        tidal_playlist = pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists)
        sync_list(spotify_session, tidal_session, [tidal_playlist], config)
    elif config.get('sync_playlists', None):
        # if the config contains a sync_playlists list of mappings then use that
        sync_list(spotify_session, tidal_session, get_playlists_from_config(config), config)
    else:
        # otherwise just use the user playlists in the Spotify account
        sync_list(spotify_session, tidal_session, get_user_playlist_mappings(spotify_session, tidal_session, config), config)
