from .config import SpotifyConfig, TidalConfig, PlaylistConfig, SyncConfig
from .spotify import SpotifyTrack
from typing import TypeAlias
from spotipy import Spotify
from tidalapi import Session, Track

TidalID: TypeAlias = str
SpotifyID: TypeAlias = str
TidalSession: TypeAlias = Session
TidalTrack: TypeAlias = Track
SpotifySession: TypeAlias = Spotify

__all__ = [
    "SpotifyConfig",
    "TidalConfig",
    "PlaylistConfig",
    "SyncConfig",
    "TidalPlaylist",
    "TidalID",
    "SpotifyID",
    "SpotifySession",
    "TidalSession",
    "TidalTrack",
    "SpotifyTrack",
]
