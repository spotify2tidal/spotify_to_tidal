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

def clear_favorites(session: tidalapi.Session):
    favorite_tracks = session.user.favorites.tracks()
    track_ids = [track.id for track in favorite_tracks]
    for track_id in track_ids:
        session.user.favorites.remove_track(track_id)

def add_multiple_tracks_to_playlist(playlist: tidalapi.UserPlaylist, session: tidalapi.Session, track_ids: List[int], chunk_size: int = 20, sync_favorites: bool = False):
    offset = 0
    with tqdm(desc="Adding new tracks to Tidal", total=len(track_ids)) as progress:
        while offset < len(track_ids):
            count = min(chunk_size, len(track_ids) - offset)
            if sync_favorites:
                for track_id in track_ids[offset:offset + chunk_size]:
                    session.user.favorites.add_track(track_id)
            else:
                playlist.add(track_ids[offset:offset + chunk_size])
            offset += count
            progress.update(count)

def set_tidal_playlist(playlist: tidalapi.Playlist, session: tidalapi.Session, track_ids: List[int], sync_favorites: bool=False):
    if sync_favorites:
        clear_favorites(session)
    else:
        clear_tidal_playlist(playlist=playlist)
    add_multiple_tracks_to_playlist(playlist=playlist, session=session, track_ids=track_ids, sync_favorites=sync_favorites)

