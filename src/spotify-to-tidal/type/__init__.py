from .config import SpotifyConfig, TidalConfig, PlaylistConfig, SyncConfig
from .playlist import TidalPlaylist
from .spotify import SpotifyTrack

from spotipy import Spotify
from tidalapi import Session, Track
from tidalapi.playlist import Playlist, UserPlaylist

TidalID = str
TidalSession = Session
TidalTrack = Track
SpotifySession = Spotify

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