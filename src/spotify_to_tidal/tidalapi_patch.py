from typing import List
import tidalapi
from tqdm import tqdm

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

def set_tidal_playlist(playlist: tidalapi.Playlist, track_ids: List[int]):
    clear_tidal_playlist(playlist)
    add_multiple_tracks_to_playlist(playlist, track_ids)
