import logging
import argparse
import sys
import yaml
from pathlib import Path
from .filters import Filter429, FilterOtherPkgs
from .auth import open_tidal_session, open_spotify_session
from .sync import sync_list
from .sync import get_tidal_playlists_dict, pick_tidal_playlist_for_spotify_playlist, get_playlists_from_config, get_user_playlist_mappings
from .type import SyncConfig

from typing import NoReturn

def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    
    parser.add_argument('-c', '--config', type=Path, help='Location of the spotify to tidal config file', dest='config')
    parser.add_argument('-i', '--id', type=str, help="Spotify client ID", dest='client_id')
    parser.add_argument('-s', '--secret', type=str, help='Spotify client secret', dest='client_secret')
    parser.add_argument('-U', '--username', type=str, help="Spotify username", dest='spotify_uname')
    parser.add_argument('-u', '--uri', help='Synchronize a specific URI instead of the one in the config', dest='uri')
    parser.add_argument('-v', help='verbosity level, increases per v specified', default=0, action='count', dest='verbosity')

    return parser

logger = None
def setup_logging(verbosity: int) -> None:
    log_map = [
        logging.WARNING,
        logging.INFO,
        logging.DEBUG
    ]
    strm_hndl = logging.StreamHandler(sys.stdout)
    strm_hndl.addFilter(Filter429('tidalapi'))
    strm_hndl.addFilter(Filter429('spotipy'))
    # strm_hndl.addFilter(FilterOtherPkgs('*'))
    
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(module)s:%(funcName)s:%(lineno)d - %(message)s')
    strm_hndl.setFormatter(fmt)
    logger = logging.getLogger(__name__)
    logger.setLevel(log_map[min(verbosity, 2)])
    logger.addHandler(strm_hndl)
    logger.debug("Initialized logging.")


def parse_args(parser: argparse.ArgumentParser) -> argparse.Namespace | NoReturn:
    args = parser.parse_args()
    setup_logging(args.verbosity)
    if args.config is None:
        logging.debug("No config specified, checking other args.")
        if args.client_id is None:
            raise RuntimeError("No config specified and Spotify client ID not specified.")
        if args.client_secret is None:
            raise RuntimeError("No config specified and Spotify secret ID not specified.")
        if args.spotify_uname is None:
            raise RuntimeError("No config specified and Spotify username not specified.")
    if args.config and any(x is not None for x in (args.client_id, args.client_secret, args.spotify_uname)):
        raise RuntimeError("Config specfied with config attributes. Only specify a config or all attributes.")
    # TODO: more validation?
    return args


def main():
    parser = setup_args()
    args = parse_args(parser)
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
