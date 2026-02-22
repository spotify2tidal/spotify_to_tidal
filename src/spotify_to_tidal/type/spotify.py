from spotipy import Spotify
from typing import TypedDict, List, Dict, Mapping, Literal, Optional


class SpotifyImage(TypedDict):
    url: str
    height: int
    width: int


class SpotifyFollower(TypedDict):
    href: str
    total: int


SpotifyID = str
SpotifySession = Spotify


class SpotifyArtist(TypedDict):
    external_urls: Mapping[str, str]
    followers: Optional[SpotifyFollower]  # Removed from API in Feb 2026
    genres: Optional[List[str]]  # Removed from API in Feb 2026
    href: str
    id: str
    images: List[SpotifyImage]
    name: str
    popularity: Optional[int]  # Removed from API in Feb 2026
    type: str
    uri: str


class SpotifyAlbum(TypedDict):
    album_type: Literal["album", "single", "compilation"]
    total_tracks: int
    available_markets: Optional[List[str]]  # Removed from API in Feb 2026
    external_urls: Dict[str, str]
    href: str
    id: str
    images: List[SpotifyImage]
    name: str
    release_date: str
    release_date_precision: Literal["year", "month", "day"]
    restrictions: Optional[Dict[Literal["reason"], str]]
    type: Literal["album"]
    uri: str
    artists: List[SpotifyArtist]


class SpotifyTrack(TypedDict):
    album: SpotifyAlbum
    artists: List[SpotifyArtist]
    available_markets: Optional[List[str]]  # Removed from API in Feb 2026
    disc_number: int
    duration_ms: int
    explicit: bool
    external_ids: Optional[Dict[str, str]]  # Removed from API in Feb 2026
    external_urls: Dict[str, str]
    href: str
    id: str
    is_playable: bool
    linked_from: Optional[Dict]  # Removed from API in Feb 2026
    restrictions: Optional[Dict[Literal["reason"], str]]
    name: str
    popularity: Optional[int]  # Removed from API in Feb 2026
    preview_url: str
    track_number: int
    type: Literal["track"]
    uri: str
