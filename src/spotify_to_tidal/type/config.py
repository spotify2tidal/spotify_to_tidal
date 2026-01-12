from collections import namedtuple
from typing import TypedDict, Literal


PlaylistIDTuple = namedtuple('PlaylistIDTuple', ['spotify_id', 'tidal_id'])
PlaylistConfigTuple = namedtuple("PlaylistConfig", ["spotify", "tidal"])
class SpotifyConfig(TypedDict):
    client_id: str
    client_secret: str
    username: str
    redirect_url: str


class TidalConfig(TypedDict):
    access_token: str
    refresh_token: str
    session_id: str
    token_type: Literal["Bearer"]


class PlaylistConfig(TypedDict):
    spotify_id: str
    tidal_id: str


class SyncSourceConfig(TypedDict):
    tidal: list[PlaylistConfig]
    SpotifyConfig: list[PlaylistConfig]

class SyncConfig(TypedDict):
    spotify: SpotifyConfig
    sync_playlists: list[PlaylistConfig] | None
    excluded_playlists: list[str] | None


