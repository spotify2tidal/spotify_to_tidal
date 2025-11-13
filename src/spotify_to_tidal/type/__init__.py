from spotipy import Spotify
from tidalapi import Session, Track

from .config import PlaylistConfig, SpotifyConfig, SyncConfig, TidalConfig
from .spotify import SpotifyTrack

TidalID = str
SpotifyID = str
TidalSession = Session
TidalTrack = Track
SpotifySession = Spotify

__all__ = [
    "SpotifyConfig",
    "TidalConfig",
    "PlaylistConfig",
    "SyncConfig",
    "TidalID",
    "SpotifyID",
    "SpotifySession",
    "TidalSession",
    "TidalTrack",
    "SpotifyTrack",
]
