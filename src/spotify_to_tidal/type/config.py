from typing import TypedDict, Literal, List, Optional


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


class SyncConfig(TypedDict):
    spotify: SpotifyConfig
    sync_playlists: Optional[List[PlaylistConfig]]
    excluded_playlists: Optional[List[str]]
    sync_favorites_default: Optional[bool]
    sync_albums_default: Optional[bool]
    max_concurrency: Optional[int]
    rate_limit: Optional[int]
    enable_fuzzy_matching: Optional[bool]
    fuzzy_name_threshold: Optional[float]
    fuzzy_artist_threshold: Optional[float]
