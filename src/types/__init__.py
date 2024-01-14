from .config import *
from .playlist import *
from .spotify import SpotifyTrack

from spotipy import Spotify
from tidalapi import Session, Track

TidalID = type[str]
SpotifyID = type[str]
SpotifySession = Spotify
TidalSession = Session
TidalTrack = Track

__all__ = [
    'SpotifyConfig',
    'TidalConfig',
    'PlaylistConfig',
    'SyncConfig',
    'TidalPlaylist',
    'TidalID',
    'SpotifyID',
    'SpotifySession',
    'TidalSession',
    'TidalTrack',
    'SpotifyTrack'
]