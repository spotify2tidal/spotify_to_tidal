import logging
import argparse
import sys
import yaml
from pathlib import Path
from .filters import Filter429, FilterOtherPkgs
from .auth import open_tidal_session, open_spotify_session
from .sync import sync_list
from .sync import (
    get_tidal_playlists_dict,
    pick_tidal_playlist_for_spotify_playlist,
    get_playlists_from_config,
    get_user_playlist_mappings,
    get_playlists_from_spotify,
)
from .type import SyncConfig, SpotifyConfig

from typing import NoReturn


def setup_args() -> argparse.ArgumentParser:
    synopsis = """
Syncs spotify playlists to Tidal. Can specify a config yaml or specify Spotify Oauth values on the command line.

"""
    parser = argparse.ArgumentParser(description=synopsis)

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Location of the spotify to tidal config file",
        dest="config",
    )
    parser.add_argument(
        "-i", "--id", type=str, help="Spotify client ID", dest="client_id"
    )
    parser.add_argument(
        "-s", "--secret", type=str, help="Spotify client secret", dest="client_secret"
    )
    parser.add_argument(
        "-U", "--username", type=str, help="Spotify username", dest="spotify_uname"
    )
    parser.add_argument(
        "-u",
        "--uri",
        help="Synchronize a specific URI instead of the one in the config",
        dest="uri",
    )
    parser.add_argument(
        "-v",
        help="verbosity level, increases per v (max of 3) specified",
        default=0,
        action="count",
        dest="verbosity",
    )
    parser.add_argument(
        "-a",
        "--all",
        help="Sync all spotify playlists to Tidal. This will not honor the config's exclude list.",
        action="store_true",
        default=False,
        dest="all_playlists",
    )

    return parser


logger = None


def setup_logging(verbosity: int) -> None:
    log_map = [logging.WARNING, logging.INFO, logging.DEBUG]
    strm_hndl = logging.StreamHandler(sys.stdout)
    strm_hndl.addFilter(Filter429("tidalapi"))
    strm_hndl.addFilter(Filter429("tidalapi.*"))
    strm_hndl.addFilter(Filter429("spotipy"))
    global logger
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(module)s:%(funcName)s:%(lineno)d - %(message)s"
    )
    strm_hndl.setFormatter(fmt)
    logger = logging.getLogger(__package__)
    logger.setLevel(log_map[min(verbosity, 2)])
    logger.addHandler(strm_hndl)
    logger.debug("Initialized logging.")


def parse_args(parser: argparse.ArgumentParser) -> argparse.Namespace | NoReturn:
    args = parser.parse_args()
    setup_logging(args.verbosity)
    if args.config is None:
        logging.debug("No config specified, checking other args.")
        if args.client_id is None:
            raise RuntimeError(
                "No config specified and Spotify client ID not specified."
            )
        if args.client_secret is None:
            raise RuntimeError(
                "No config specified and Spotify secret ID not specified."
            )
        if args.spotify_uname is None:
            raise RuntimeError(
                "No config specified and Spotify username not specified."
            )
    if args.config and any(
        x is not None for x in (args.client_id, args.client_secret, args.spotify_uname)
    ):
        raise RuntimeError(
            "Config specfied with config attributes. Only specify a config or all attributes."
        )
    # TODO: more validation?
    return args


def main():
    parser = setup_args()
    args = parse_args(parser)
    if args.config:
        with open(args.config, "r") as f:
            config: SyncConfig = yaml.safe_load(f)
            spt_cfg: SpotifyConfig = config['spotify']
    else:
        spt_cfg: SpotifyConfig = {
            'client_id': args.client_id,
            'client_secret': args.client_secret,
            'username': args.spotify_uname,
            'redirect_uri': 'http://localhost:8888/callback',
        }
    spotify_session = open_spotify_session(spt_cfg)
    tidal_session = open_tidal_session()
    if not tidal_session.check_login():
        logging.critical("Could not connect to Tidal")
        sys.exit(1)
    if args.uri:
        # if a playlist ID is explicitly provided as a command line argument then use that
        spotify_playlist = spotify_session.playlist(args.uri)
        tidal_playlists = get_tidal_playlists_dict(tidal_session)
        tidal_playlist = pick_tidal_playlist_for_spotify_playlist(
            spotify_playlist, tidal_playlists
        )
        sync_list(spotify_session, tidal_session, [tidal_playlist], config)

    elif args.all_playlists:
        playlists = []
        cursor = spotify_session.current_user_playlists()
        while True:
            playlists.extend(cursor["items"])
            if not cursor["next"]:
                break
            cursor = spotify_session.next(cursor)

        tidal_playlists = {p.name: p for p in tidal_session.user.playlists()}
        id_map = []
        for sp_playlist in playlists:
            # Check if playlist exists
            if (p_name := sp_playlist["name"]) in tidal_playlists:
                tid = tidal_playlists[p_name].id
            else:
                tid = None
                id_map.append((sp_playlist["id"], tid))
        logger.info("Syncing %d playlists", len(id_map))
        sync_list(spotify_session, tidal_session, id_map, config)
    elif config.get("sync_playlists", None):
        # if the config contains a sync_playlists list of mappings then use that
        sync_list(
            spotify_session, tidal_session, get_playlists_from_config(config), config
        )
    else:
        # otherwise just use the user playlists in the Spotify account
        sync_list(
            spotify_session,
            tidal_session,
            get_user_playlist_mappings(spotify_session, tidal_session, config),
            config,
        )
