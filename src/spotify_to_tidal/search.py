import tidalapi
import tidalapi.session

from cachetools import TTLCache, cached

def simple(input_string: str) -> str:
    # only take the first part of a string before any hyphens or brackets to account for different versions
    return input_string.split('-')[0].strip().split('(')[0].strip().split('[')[0].strip()

# We simplify the search to easily cache results

@cached(TTLCache(maxsize=1024, ttl=600))
def _search_tidal(
    tidal_session: tidalapi.Session,
    q: str,
    model: tidalapi.Album | tidalapi.Track | tidalapi.Artist
    ) -> tidalapi.session.SearchResults:
    return tidal_session.search(q, models=[model])

@cached(TTLCache(maxsize=1024, ttl=600))
def search_tidal_albums(tidal_session: tidalapi.Session, artist: str, album: str):
    artist = simple(artist.casefold())
    album = simple(album.casefold())
    return _search_tidal(tidal_session, artist+" "+album, tidalapi.Album)

@cached(TTLCache(maxsize=1024, ttl=600))
def search_tidal_tracks(tidal_session: tidalapi.Session, artist: str, track: str):
    artist = simple(artist.casefold())
    track = simple(track.casefold())
    return _search_tidal(tidal_session, artist+" "+track, tidalapi.Track)
