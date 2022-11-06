from tqdm import tqdm
def set_tidal_playlist(session, playlist_id, track_ids):
    # erases any items in the given playlist, then adds all of the tracks given in track_ids
    # had to hack this together because the API doesn't include it

    chunk_size = 20 # add/delete tracks in chunks of no more than this many tracks

    # clear all old items from playlist
    playlist = session.playlist(playlist_id)
    progress = tqdm(desc="Erasing existing tracks from Tidal playlist", total=playlist.num_tracks)
    while True:
        if not playlist.num_tracks:
            break
        playlist.remove_by_index(0)
        progress.update(playlist.num_tracks)
        playlist = session.playlist(playlist_id)
    progress.close()

    # add all new items to the playlist
    offset = 0
    progress = tqdm(desc="Adding new tracks to Tidal playlist", total=len(track_ids))
    while offset < len(track_ids):
        count = min(chunk_size, len(track_ids) - offset)
        playlist.add(track_ids[offset:offset+chunk_size])
        offset += count
        progress.update(count)
    progress.close()
