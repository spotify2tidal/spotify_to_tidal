import tidalapi
import tidalapi.session

def simple(input_string: str) -> str:
    # only take the first part of a string before any hyphens or brackets to account for different versions
    return input_string.split('-')[0].strip().split('(')[0].strip().split('[')[0].strip()

# We simplify the search to easily cache results

def _search_tidal(
    tidal_session: tidalapi.Session,
    q: str,
    model: tidalapi.Album | tidalapi.Track | tidalapi.Artist
    ) -> tidalapi.session.SearchResults:
    return tidal_session.search(q, models=[model])

def search_tidal_albums(tidal_session: tidalapi.Session, artist: str, album: str):
    artist = simple(artist.casefold())
    album = simple(album.casefold())
    return _search_tidal(tidal_session, artist+" "+album, tidalapi.Album)

def search_tidal_tracks(tidal_session: tidalapi.Session, artist: str, track: str):
    artist = simple(artist.casefold())
    track = simple(track.casefold())
    return _search_tidal(tidal_session, artist+" "+track, tidalapi.Track)
