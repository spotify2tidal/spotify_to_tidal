import asyncio
import math
from typing import Callable, List, Sequence
import requests
import tidalapi
from tqdm import tqdm
from tqdm.asyncio import tqdm as atqdm

from .ratelimit import repeat_on_request_error

async def _mutate_playlist_chunk(playlist, op: Callable, *args, attempts: int = 5):
    """ Apply one chunked playlist mutation via a tidalapi method (UserPlaylist.add /
        remove_by_indices). Those methods send the If-None-Match ETag and refresh it after each call,
        but Tidal still intermittently rejects a freshly-refreshed ETag under rapid consecutive writes
        (412 subStatus 7002), and the library doesn't retry — so on a 412 we refresh the ETag and retry
        the same chunk. Rate-limit / transient errors flow through repeat_on_request_error. """
    for attempt in range(attempts):
        try:
            return await repeat_on_request_error(asyncio.to_thread, op, *args)
        except requests.exceptions.HTTPError as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status == 412 and attempt < attempts - 1:
                await asyncio.sleep(1 + attempt)  # let the ETag replica catch up, then refresh and retry
                await asyncio.to_thread(playlist._reparse)
                continue
            raise

async def clear_tidal_playlist(playlist: tidalapi.UserPlaylist, chunk_size: int=20):
    """ Erase a Tidal playlist in chunks via the library's remove_by_indices, retrying each chunk on a
        stale-ETag 412. """
    with tqdm(desc="Erasing existing tracks from Tidal playlist", total=playlist.num_tracks) as progress:
        while playlist.num_tracks:
            indices = range(min(playlist.num_tracks, chunk_size))
            await _mutate_playlist_chunk(playlist, playlist.remove_by_indices, indices)
            progress.update(len(indices))

async def add_tracks_to_tidal_playlist(playlist: tidalapi.Playlist, track_ids: Sequence[int], chunk_size: int = 20):
    """ Append tracks to a Tidal playlist in chunks via the library's add, retrying each chunk on a
        stale-ETag 412. """
    with tqdm(desc="Adding new tracks to Tidal playlist", total=len(track_ids)) as progress:
        for offset in range(0, len(track_ids), chunk_size):
            chunk = track_ids[offset:offset + chunk_size]
            await _mutate_playlist_chunk(playlist, playlist.add, chunk)
            progress.update(len(chunk))

async def _get_all_chunks(url, session, parser, params={}) -> List[tidalapi.Track]:
    """ 
        Helper function to get all items from a Tidal endpoint in parallel
        The main library doesn't provide the total number of items or expose the raw json, so use this wrapper instead
    """
    def _make_request(offset: int=0):
        # copy per call: these run concurrently via asyncio.to_thread and would otherwise race on
        # the shared params dict (and mutate the caller's / the default dict)
        new_params = dict(params)
        new_params['offset'] = offset
        return session.request.map_request(url, params=new_params)

    first_chunk_raw = _make_request()
    limit = first_chunk_raw['limit']
    total = first_chunk_raw['totalNumberOfItems']
    items = session.request.map_json(first_chunk_raw, parse=parser)

    if len(items) < total:
        offsets = [limit * n for n in range(1, math.ceil(total/limit))]
        extra_results = await atqdm.gather(
                *[asyncio.to_thread(lambda offset: session.request.map_json(_make_request(offset), parse=parser), offset) for offset in offsets],
            desc="Fetching additional data chunks"
        )
        for extra_result in extra_results:
            items.extend(extra_result)
    return items

async def get_all_favorites(favorites: tidalapi.Favorites, order: str = "NAME", order_direction: str = "ASC", chunk_size: int=100) -> List[tidalapi.Track]:
    """ Get all favorites from Tidal playlist in chunks """
    params = {
        "limit": chunk_size,
        "order": order,
        "orderDirection": order_direction,
    }
    return await _get_all_chunks(f"{favorites.base_url}/tracks", session=favorites.session, parser=favorites.session.parse_track, params=params)

async def get_all_playlists(user: tidalapi.User, chunk_size: int=10) -> List[tidalapi.Playlist]:
    """ Get all user playlists from Tidal in chunks """
    print(f"Loading playlists from Tidal user")
    params = {
        "limit": chunk_size,
    }
    return await _get_all_chunks(f"users/{user.id}/playlists", session=user.session, parser=user.playlist.parse_factory, params=params)

async def get_all_playlist_tracks(playlist: tidalapi.Playlist, chunk_size: int=20) -> List[tidalapi.Track]:
    """ Get all tracks from Tidal playlist in chunks """
    params = {
        "limit": chunk_size,
    }
    print(f"Loading tracks from Tidal playlist '{playlist.name}'")
    return await _get_all_chunks(f"{playlist._base_url%playlist.id}/tracks", session=playlist.session, parser=playlist.session.parse_track, params=params)

async def get_all_saved_albums(user: tidalapi.User) -> List[tidalapi.Album]:
    """ Get all saved albums from Tidal user favorites """
    print(f"Loading saved albums from Tidal")
    return await asyncio.to_thread(user.favorites.albums_paginated)

def add_album_to_tidal_collection(session: tidalapi.Session, album_id: str):
    """ Add album to user's Tidal favorites """
    return session.user.favorites.add_album(album_id)

async def get_all_saved_artists(user: tidalapi.User) -> List[tidalapi.Artist]:
    """ Get all followed artists from Tidal user favorites """
    print(f"Loading followed artists from Tidal")
    return await asyncio.to_thread(user.favorites.artists_paginated)

def add_artist_to_tidal_collection(session: tidalapi.Session, artist_id: str):
    """ Add artist to user's Tidal favorites """
    return session.user.favorites.add_artist(artist_id)

