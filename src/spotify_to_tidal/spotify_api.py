""" Spotify read access: paginated fetchers for playlist tracks, followed artists and the user's
    playlists. Mirrors tidalapi_patch.py on the Tidal side. All calls go through
    repeat_on_request_error so transient/rate-limit errors are retried. """

import asyncio
import math
from typing import Callable, List

import spotipy
from tqdm.asyncio import tqdm as atqdm

from .ratelimit import repeat_on_request_error


async def _fetch_all_from_spotify_in_chunks(fetch_function: Callable, item_key: str = "track") -> List[dict]:
    output = []
    results = fetch_function(0)
    output.extend([item[item_key] for item in results['items'] if item.get(item_key) is not None])

    # Get all the remaining items in parallel
    if results['next']:
        offsets = [results['limit'] * n for n in range(1, math.ceil(results['total'] / results['limit']))]
        extra_results = await atqdm.gather(
            *[asyncio.to_thread(fetch_function, offset) for offset in offsets],
            desc="Fetching additional data chunks"
        )
        for extra_result in extra_results:
            output.extend([item[item_key] for item in extra_result['items'] if item.get(item_key) is not None])

    return output


async def get_tracks_from_spotify_playlist(spotify_session: spotipy.Spotify, spotify_playlist):
    def _get_tracks_from_spotify_playlist(offset: int, playlist_id: str):
        fields = "next,total,limit,items(track(name,album(name,artists(id,name)),artists(id,name),track_number,duration_ms,id,external_ids(isrc))),type"
        return spotify_session.playlist_tracks(playlist_id=playlist_id, fields=fields, offset=offset)

    print(f"Loading tracks from Spotify playlist '{spotify_playlist['name']}'")
    items = await repeat_on_request_error( _fetch_all_from_spotify_in_chunks, lambda offset: _get_tracks_from_spotify_playlist(offset=offset, playlist_id=spotify_playlist["id"]))
    track_filter = lambda item: item.get('type', 'track') == 'track' # type may be 'episode' also
    sanity_filter = lambda item: ('album' in item
                                  and 'name' in item['album']
                                  and 'artists' in item['album']
                                  and len(item['album']['artists']) > 0
                                  and item['album']['artists'][0]['name'] is not None)
    return list(filter(sanity_filter, filter(track_filter, items)))


async def get_followed_artists_from_spotify(spotify_session: spotipy.Spotify) -> List[dict]:
    """ Fetch all artists the user follows on Spotify (cursor-paginated). """
    async def _fetch_all_artists_from_spotify_in_chunks(fetch_function: Callable) -> List[dict]:
        output = []
        results = fetch_function(limit=50)
        if results and 'artists' in results:
            output.extend([item for item in results['artists']['items'] if item is not None])

            # Handle pagination
            while results['artists']['next']:
                after = results['artists']['cursors']['after']
                if not after:
                    break  # no cursor to advance with; stop rather than re-requesting the same page
                results = fetch_function(limit=50, after=after)
                if results and 'artists' in results:
                    output.extend([item for item in results['artists']['items'] if item is not None])
                else:
                    break
        return output

    _get_followed_artists = lambda **kwargs: spotify_session.current_user_followed_artists(**kwargs)
    return await repeat_on_request_error(_fetch_all_artists_from_spotify_in_chunks, _get_followed_artists)


async def get_playlists_from_spotify(spotify_session: spotipy.Spotify, config):
    # get all the playlists from the Spotify account
    playlists = []
    print("Loading Spotify playlists")
    first_results = await repeat_on_request_error(asyncio.to_thread, spotify_session.current_user_playlists)
    exclude_list = set([x.split(':')[-1] for x in config.get('excluded_playlists', [])])
    playlists.extend([p for p in first_results['items']])
    user_id = (await repeat_on_request_error(asyncio.to_thread, spotify_session.current_user))['id']

    # get all the remaining playlists in parallel
    if first_results['next']:
        offsets = [ first_results['limit'] * n for n in range(1, math.ceil(first_results['total']/first_results['limit'])) ]
        extra_results = await atqdm.gather( *[repeat_on_request_error(asyncio.to_thread, spotify_session.current_user_playlists, offset=offset) for offset in offsets ] )
        for extra_result in extra_results:
            playlists.extend([p for p in extra_result['items']])

    # filter out playlists that don't belong to us or are on the exclude list
    my_playlist_filter = lambda p: p and p['owner']['id'] == user_id
    exclude_filter = lambda p: not p['id'] in exclude_list
    return list(filter( exclude_filter, filter( my_playlist_filter, playlists )))
