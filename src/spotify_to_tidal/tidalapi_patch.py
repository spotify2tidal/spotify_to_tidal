import asyncio
import math
from typing import List
import tidalapi
from tqdm import tqdm
from tqdm.asyncio import tqdm as atqdm

def _remove_indices_from_playlist(playlist: tidalapi.UserPlaylist, indices: List[int]):
    headers = {'If-None-Match': playlist._etag}
    index_string = ",".join(map(str, indices))
    playlist.request.request('DELETE', (playlist._base_url + '/items/%s') % (playlist.id, index_string), headers=headers)
    playlist._reparse()

def clear_tidal_playlist(playlist: tidalapi.UserPlaylist, chunk_size: int=20):
    with tqdm(desc="Erasing existing tracks from Tidal playlist", total=playlist.num_tracks) as progress:
        while playlist.num_tracks:
            indices = range(min(playlist.num_tracks, chunk_size))
            _remove_indices_from_playlist(playlist, indices)
            progress.update(len(indices))
    
def add_multiple_tracks_to_playlist(playlist: tidalapi.UserPlaylist, track_ids: List[int], chunk_size: int=20):
    offset = 0
    with tqdm(desc="Adding new tracks to Tidal playlist", total=len(track_ids)) as progress:
        while offset < len(track_ids):
            count = min(chunk_size, len(track_ids) - offset)
            playlist.add(track_ids[offset:offset+chunk_size])
            offset += count
            progress.update(count)

async def get_all_favorites(favorites: tidalapi.Favorites, order: str = "NAME", order_direction: str = "ASC",) -> List[tidalapi.Track]:
    """ Get all favorites from Tidal playlist in chunks. The main library doesn't provide the total number of items or expose the raw json, so need this wrapper """
    params = {
        "limit": None,
        "offset": 0,
        "order": order,
        "orderDirection": order_direction,
    }
    first_chunk_raw = favorites.requests.map_request(f"{favorites.base_url}/tracks", params)
    limit = first_chunk_raw['limit']
    total = first_chunk_raw['totalNumberOfItems']
    tracks = favorites.session.request.map_json(first_chunk_raw, parse=favorites.session.parse_track)

    if len(tracks) < total:
        offsets = [limit * n for n in range(1, math.ceil(total/limit))]
        extra_results = await atqdm.gather(
                *[asyncio.to_thread(lambda offset: favorites.tracks(offset=offset, order=order, order_direction=order_direction), offset) for offset in offsets],
            desc="Fetching additional data chunks"
        )
        for extra_result in extra_results:
            tracks.extend(extra_result)
    return tracks
