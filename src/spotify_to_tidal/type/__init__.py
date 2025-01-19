from .config import SpotifyConfig, TidalConfig, PlaylistConfig, SyncConfig, PlaylistIDTuple, PlaylistConfigTuple
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
    "PlaylistConfig",
    "PlaylistConfigTuple",
    "PlaylistIDTuple",
    "SpotifyConfig",
    "SpotifyID",
    "SpotifySession",
    "SpotifyTrack",
    "SyncConfig",
    "TidalID",
    "TidalConfig",
    "TidalSession",
    "TidalTrack",
]
