""" Pure cross-platform matching helpers: text normalization and the track / album / artist
    similarity functions. No network or cache access — safe to import anywhere. """

from difflib import SequenceMatcher
from typing import Optional, Sequence, Set
import unicodedata

import tidalapi

from .type import spotify as t_spotify


def normalize(s) -> str:
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')

def simple(input_string: str) -> list[str]:
    """
    Simple progressive text normalization for matching across platforms.
    Returns two variations: exact (normalized) and simplified (without parentheses).

    Args:
        input_string: Text to simplify

    Returns:
        List with [exact_normalized, simplified] versions
    """
    if not input_string:
        return [""]

    text = input_string.strip()

    # Exact: just normalize whitespace and dashes
    exact = ' '.join(text.split()).replace('–', '-').replace('—', '-').replace('−', '-')

    # Simplified: remove everything in parentheses/brackets
    simplified = text.split('(')[0].split('[')[0].strip()
    simplified = ' '.join(simplified.split()).replace('–', '-').replace('—', '-').replace('−', '-')

    # Return both variations, avoiding duplicates
    if exact == simplified:
        return [exact]
    else:
        return [exact, simplified]

def isrc_match(tidal_track: tidalapi.Track, spotify_track) -> bool:
    if "isrc" in spotify_track["external_ids"]:
        return tidal_track.isrc == spotify_track["external_ids"]["isrc"]
    return False

def duration_match(tidal_track: tidalapi.Track, spotify_track, tolerance=2) -> bool:
    # the duration of the two tracks must be the same to within 2 seconds
    return abs(tidal_track.duration - spotify_track['duration_ms']/1000) < tolerance

def name_match(tidal_track, spotify_track) -> bool:
    def exclusion_rule(pattern: str, tidal_track: tidalapi.Track, spotify_track: t_spotify.SpotifyTrack):
        spotify_has_pattern = pattern in spotify_track['name'].lower()
        tidal_has_pattern = pattern in tidal_track.name.lower() or (not tidal_track.version is None and (pattern in tidal_track.version.lower()))
        return spotify_has_pattern != tidal_has_pattern

    # handle some edge cases
    if exclusion_rule("instrumental", tidal_track, spotify_track): return False
    if exclusion_rule("acapella", tidal_track, spotify_track): return False
    if exclusion_rule("remix", tidal_track, spotify_track): return False

    # the simplified version of the Spotify track name must be a substring of the Tidal track name
    # Try with both un-normalized and then normalized
    simple_spotify_track = simple(spotify_track['name'])[0].lower().split('feat.')[0].strip()
    return simple_spotify_track in tidal_track.name.lower() or normalize(simple_spotify_track) in normalize(tidal_track.name.lower())

def artists_overlap(tidal: tidalapi.Track | tidalapi.Album, spotify) -> bool:
    def split_artist_name(artist: str) -> Sequence[str]:
       if '&' in artist:
           return artist.split('&')
       elif ',' in artist:
           return artist.split(',')
       elif ' and ' in artist.lower():
           return artist.lower().split(' and ')
       else:
           return [artist]

    def get_tidal_artists(tidal: tidalapi.Track | tidalapi.Album, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in tidal.artists:
            if do_normalize:
                artist_name = normalize(artist.name)
            else:
                artist_name = artist.name
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip())[0].lower() for x in result])

    def get_spotify_artists(spotify, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in spotify['artists']:
            if do_normalize:
                artist_name = normalize(artist['name'])
            else:
                artist_name = artist['name']
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip())[0].lower() for x in result])
    # There must be at least one overlapping artist between the Tidal and Spotify track
    # Try with both un-normalized and then normalized
    if get_tidal_artists(tidal).intersection(get_spotify_artists(spotify)) != set():
        return True
    return get_tidal_artists(tidal, True).intersection(get_spotify_artists(spotify, True)) != set()

def match(tidal_track, spotify_track) -> bool:
    if not spotify_track['id']: return False
    return isrc_match(tidal_track, spotify_track) or (
        duration_match(tidal_track, spotify_track)
        and name_match(tidal_track, spotify_track)
        and artists_overlap(tidal_track, spotify_track)
    )

def test_album_similarity(spotify_album, tidal_album, threshold=0.6):
    spotify_simple = simple(spotify_album['name'])[0]
    tidal_simple = simple(tidal_album.name)[0]
    return SequenceMatcher(None, spotify_simple, tidal_simple).ratio() >= threshold and artists_overlap(tidal_album, spotify_album)

def _names_match(spotify_name: str, tidal_name: str, config: Optional[dict] = None,
                 threshold_key: str = 'fuzzy_name_threshold', default_threshold: float = 0.85) -> bool:
    """ Compare two names using progressive simplification, unicode normalization and
        optional fuzzy matching. Shared by artist matching and album name/artist matching. """
    fuzzy_threshold = config.get(threshold_key, default_threshold) if config else default_threshold
    for spotify_var in simple(spotify_name):
        for tidal_var in simple(tidal_name):
            spotify_lower = spotify_var.lower()
            tidal_lower = tidal_var.lower()

            # Exact / substring match
            if spotify_lower == tidal_lower or spotify_lower in tidal_lower or tidal_lower in spotify_lower:
                return True

            # Unicode normalized match
            norm_spotify = normalize(spotify_lower)
            norm_tidal = normalize(tidal_lower)
            if norm_spotify == norm_tidal or norm_spotify in norm_tidal or norm_tidal in norm_spotify:
                return True

            # Fuzzy matching (if enabled)
            if config and config.get('enable_fuzzy_matching', False):
                if (SequenceMatcher(None, spotify_lower, tidal_lower).ratio() >= fuzzy_threshold
                        or SequenceMatcher(None, norm_spotify, norm_tidal).ratio() >= fuzzy_threshold):
                    return True
    return False

def album_match(tidal_album: tidalapi.Album, spotify_album: dict, config: Optional[dict] = None) -> bool:
    """ Check if a Tidal album matches a Spotify album using progressive matching """
    # Album name must match (progressive simplification preserves edition info)
    if not _names_match(spotify_album['name'], tidal_album.name, config, default_threshold=0.80):
        return False

    # Artist matching using progressive simplification
    def get_artists(album):
        """Extract artist names from an album"""
        if hasattr(album, 'artists'):  # Tidal album
            return [artist.name for artist in album.artists]
        else:  # Spotify album
            return [artist['name'] for artist in album['artists']]

    def split_artists(artist_names):
        """Split artist names on common separators"""
        result = []
        for artist_name in artist_names:
            if '&' in artist_name:
                result.extend(artist_name.split('&'))
            elif ',' in artist_name:
                result.extend(artist_name.split(','))
            elif ' and ' in artist_name.lower():
                result.extend([part for part in artist_name.lower().split(' and ')])
            else:
                result.append(artist_name)
        return [name.strip() for name in result]

    tidal_artists = split_artists(get_artists(tidal_album))
    spotify_artists = split_artists(get_artists(spotify_album))

    # There must be at least one overlapping artist between the two albums
    for tidal_artist in tidal_artists:
        for spotify_artist in spotify_artists:
            if _names_match(spotify_artist, tidal_artist, config,
                            threshold_key='fuzzy_artist_threshold', default_threshold=0.75):
                return True
    return False

def artist_match(tidal_artist: tidalapi.Artist, spotify_artist: dict, config: Optional[dict] = None) -> bool:
    """ Check if a Tidal artist matches a Spotify artist using progressive matching """
    return _names_match(spotify_artist['name'], tidal_artist.name, config, default_threshold=0.85)
