import tidalapi
from tqdm import tqdm

tidalapi_parse_album = tidalapi._parse_album


def patch():
    tidalapi._parse_album = _parse_album
    tidalapi.models.Album.picture = picture


def _parse_album(json_obj, artist=None, artists=None):
    obj = tidalapi_parse_album(json_obj, artist, artists)
    image_id = ""
    if json_obj.get("cover"):
        image_id = json_obj.get("cover")

    obj.__dict__.update(image_id=image_id)
    return obj


def picture(obj, width, height):
    return "https://resources.tidal.com/images/{image_id}/{width}x{height}.jpg".format(
        image_id=obj.image_id.replace("-", "/"), width=width, height=height
    )

def set_tidal_playlist(session, playlist_id, track_ids):
    # erases any items in the given playlist, then adds all of the tracks given in track_ids
    # had to hack this together because the API doesn't include it

    chunk_size = 20 # add/delete tracks in chunks of no more than this many tracks
    request_params = {
        'sessionId': session.session_id,
        'countryCode': session.country_code,
        'limit': '999',
    }
    def get_headers():
        etag = session.request('GET','playlists/%s/tracks' % playlist_id).headers['ETag']
        return {'if-none-match' : etag}

    # clear all old items from playlist
    playlist = session.get_playlist(playlist_id)
    progress = tqdm(desc="Erasing existing tracks from Tidal playlist", total=playlist.num_tracks)
    while True:
        if not playlist.num_tracks:
            break
        track_index_string = ",".join([str(x) for x in range(min(chunk_size, playlist.num_tracks))])
        result = session.request('DELETE', 'playlists/{}/tracks/{}'.format(playlist.id, track_index_string), params=request_params, headers=get_headers())
        result.raise_for_status()
        progress.update(min(chunk_size, playlist.num_tracks))
        playlist = session.get_playlist(playlist_id)
    progress.close()

    # add all new items to the playlist
    offset = 0
    progress = tqdm(desc="Adding new tracks to Tidal playlist", total=len(track_ids))
    while offset < len(track_ids):
        count = min(chunk_size, len(track_ids) - offset)
        data = {
            'trackIds' : ",".join([str(x) for x in track_ids[offset:offset+chunk_size]]),
            'toIndex' : offset
        }
        offset += count
        result = session.request('POST', 'playlists/{}/tracks'.format(playlist.id), params=request_params, data=data, headers=get_headers())
        result.raise_for_status()
        progress.update(count)
    progress.close()

def create_tidal_playlist(session, name):
    result = session.request('POST','users/%s/playlists' % session.user.id ,data={'title': name})
    return session.get_playlist(result.json()['uuid'])

def delete_tidal_playlist(session, playlist):
    etag = session.request('GET','playlists/%s' % playlist.id).headers['ETag']
    headers = {'if-none-match' : etag}
    session.request('DELETE','playlists/%s' % playlist.id, headers=headers)
