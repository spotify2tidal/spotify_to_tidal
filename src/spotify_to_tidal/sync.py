#!/usr/bin/env python3

from .cache import failure_cache, track_match_cache
from functools import partial
from typing import List, Sequence, Set, Mapping
import math
from multiprocessing import Pool
import requests
import sys
import spotipy
import tidalapi
from .tidalapi_patch import set_tidal_playlist
import time
from tqdm import tqdm
import traceback
import unicodedata

from .type import spotify as t_spotify

# maintain compatibility on 3.10, `Self` requires 3.11
try:
    from typing import Self
except ImportError:
    from typing import Any, TypeAlias
    Self: TypeAlias = Any

def normalize(s) -> str:
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')

def simple(input_string: str) -> str:
    # only take the first part of a string before any hyphens or brackets to account for different versions
    return input_string.split('-')[0].strip().split('(')[0].strip().split('[')[0].strip()

def isrc_match(tidal_track: tidalapi.Track, spotify_track) -> bool:
    if "isrc" in spotify_track["external_ids"]:
        return tidal_track.isrc == spotify_track["external_ids"]["isrc"]
    return False

def duration_match(tidal_track: tidalapi.Track, spotify_track, tolerance=2) -> float:
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
    simple_spotify_track = simple(spotify_track['name'].lower()).split('feat.')[0].strip()
    return simple_spotify_track in tidal_track.name.lower() or normalize(simple_spotify_track) in normalize(tidal_track.name.lower())

def artist_match(tidal_track: tidalapi.Track, spotify_track) -> Set[str]:
    def split_artist_name(artist: str) -> Sequence[str]:
       if '&' in artist:
           return artist.split('&')
       elif ',' in artist:
           return artist.split(',')
       else:
           return [artist]

    def get_tidal_artists(tidal_track: tidalapi.Track, do_normalize=False) -> Set[str]:
        result = []
        for artist in tidal_track.artists:
            if do_normalize:
                artist_name = normalize(artist.name)
            else:
                artist_name = artist.name
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip().lower()) for x in result])

    def get_spotify_artists(spotify_track: t_spotify.SpotifyTrack, do_normalize=False) -> Set[str]:
        result = []
        for artist in spotify_track['artists']:
            if do_normalize:
                artist_name = normalize(artist['name'])
            else:
                artist_name = artist['name']
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip().lower()) for x in result])
    # There must be at least one overlapping artist between the Tidal and Spotify track
    # Try with both un-normalized and then normalized
    if get_tidal_artists(tidal_track).intersection(get_spotify_artists(spotify_track)) != set():
        return True
    return get_tidal_artists(tidal_track, True).intersection(get_spotify_artists(spotify_track, True)) != set()

def match(tidal_track, spotify_track) -> bool:
    return isrc_match(tidal_track, spotify_track) or (
        duration_match(tidal_track, spotify_track)
        and name_match(tidal_track, spotify_track)
        and artist_match(tidal_track, spotify_track)
    )

def tidal_search(spotify_track_and_cache, tidal_session: tidalapi.Session) -> int | None:
    spotify_track, cached_tidal_track_id = spotify_track_and_cache
    if cached_tidal_track_id: return cached_tidal_track_id
    if spotify_track['id'] is None: return None
    if failure_cache.has_match_failure(spotify_track['id']):
        return None
    # search for album name and first album artist
    if 'album' in spotify_track and 'artists' in spotify_track['album'] and len(spotify_track['album']['artists']):
        album_result = tidal_session.search(simple(spotify_track['album']['name']) + " " + simple(spotify_track['album']['artists'][0]['name']), models=[tidalapi.album.Album])
        for album in album_result['albums']:
            album_tracks = album.tracks()
            if len(album_tracks) >= spotify_track['track_number']:
                track = album_tracks[spotify_track['track_number'] - 1]
                if match(track, spotify_track):
                    failure_cache.remove_match_failure(spotify_track['id'])
                    return track.id
    # if that fails then search for track name and first artist
    for track in tidal_session.search(simple(spotify_track['name']) + ' ' + simple(spotify_track['artists'][0]['name']), models=[tidalapi.media.Track])['tracks']:
        if match(track, spotify_track):
            failure_cache.remove_match_failure(spotify_track['id'])
            return track.id
    failure_cache.cache_match_failure(spotify_track['id'])

def get_tidal_playlists_dict(tidal_session: tidalapi.Session) -> Mapping[str, tidalapi.Playlist]:
    # a dictionary of name --> playlist
    print("Loading Tidal playlists... This may take some time.")
    tidal_playlists = tidal_session.user.playlists()
    output = {}
    for playlist in tidal_playlists:
        output[playlist.name] = playlist
    return output 

def repeat_on_request_error(function, *args, remaining=5, **kwargs):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    try:
        return function(*args, **kwargs)
    except requests.exceptions.RequestException as e:
        if remaining:
            print(f"{str(e)} occurred, retrying {remaining} times")
        else:
            print(f"{str(e)} could not be recovered")

        if not e.response is None:
            print(f"Response message: {e.response.text}")
            print(f"Response headers: {e.response.headers}")

        if not remaining:
            print("Aborting sync")
            print(f"The following arguments were provided:\n\n {str(args)}")
            print(traceback.format_exc())
            sys.exit(1)
        sleep_schedule = {5: 1, 4:10, 3:60, 2:5*60, 1:10*60} # sleep variable length of time depending on retry number
        time.sleep(sleep_schedule.get(remaining, 1))
        return repeat_on_request_error(function, *args, remaining=remaining-1, **kwargs)

def call_async_with_progress(function, values, description, num_processes, **kwargs):
    with Pool(processes=num_processes) as process_pool:
        results = [process_pool.apply_async(repeat_on_request_error, args=(function, value), kwds=kwargs) for value in values]
        return [r.get() for r in tqdm(results, desc=description)]

def _get_tracks_from_spotify_playlist(offset: int, spotify_session: spotipy.Spotify, playlist_id: str):
    """ implementation function for use with multiprocessing module """
    fields="next,total,limit,items(track(name,album(name,artists),artists,track_number,duration_ms,id,external_ids(isrc)))"
    return spotify_session.playlist_tracks(playlist_id, fields, offset=offset)

def get_tracks_from_spotify_playlist(spotify_session: spotipy.Spotify, spotify_playlist):
    output = []
    print(f"Loading tracks from Spotify playlist '{spotify_playlist['name']}'")
    results = _get_tracks_from_spotify_playlist( 0, spotify_session, spotify_playlist["id"] )
    output.extend([r['track'] for r in results['items'] if r['track'] is not None])

    # get all the remaining tracks in parallel
    if results['next']:
        offsets = [ results['limit'] * n for n in range(1, math.ceil(results['total']/results['limit'])) ]
        extra_results = call_async_with_progress(_get_tracks_from_spotify_playlist, offsets, "",
                                                 min(len(offsets), 10), spotify_session=spotify_session, playlist_id=spotify_playlist["id"])
        for extra_result in extra_results:
            output.extend([r['track'] for r in extra_result['items'] if r['track'] is not None])
    return output


def tidal_playlist_is_dirty(old_tracks: List[tidalapi.Track], new_track_ids: Sequence[str|None]) -> bool:
    return list(filter(lambda x: not x is None, new_track_ids) ) == [x.id for x in old_tracks]

def populate_track_match_cache(spotify_tracks: List[t_spotify.SpotifyTrack], tidal_tracks: List[tidalapi.Track]):
    """ Populate the track match cache with all the existing tracks in Tidal playlist corresponding to Spotify playlist """
    def _populate_one_track(spotify_track: t_spotify.SpotifyTrack, tidal_tracks: List[tidalapi.Track]) -> bool:
        for idx, tidal_track in list(enumerate(tidal_tracks)):
            if match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                tidal_tracks.pop(idx)
                return True
        return False

    for track in spotify_tracks:
        if track_match_cache.get(track['id']):
            continue
        _populate_one_track(track, tidal_tracks)

def search_track_match_cache(spotify_tracks):
    ''' Seaches the tidal track cache and adds the cached tidal track where applicable to list of spotify tracks '''
    results = []
    cache_hits = 0
    for spotify_track in spotify_tracks:
        cached_track_id = track_match_cache.get(spotify_track["id"])
        if cached_track_id:
            results.append( (spotify_track, cached_track_id) )
            cache_hits += 1
        else:
            results.append( (spotify_track, None) )
    return (results, cache_hits)

def sync_playlist(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_playlist, tidal_playlist: tidalapi.Playlist | None, config):
    if not tidal_playlist:
        # create a new Tidal playlist if required
        print(f"No playlist found on Tidal corresponding to Spotify playlist: '{spotify_playlist['name']}', creating new playlist")
        tidal_playlist =  tidal_session.user.create_playlist(spotify_playlist['name'], spotify_playlist['description'])

    new_tidal_track_ids = []
    spotify_tracks = get_tracks_from_spotify_playlist(spotify_session, spotify_playlist)
    old_tidal_tracks = tidal_playlist.tracks()
    populate_track_match_cache(spotify_tracks, old_tidal_tracks)
    spotify_track_mappings, cache_hits = search_track_match_cache(spotify_tracks)

    if cache_hits == len(spotify_tracks):
        print("No new tracks to search in Spotify playlist '{}'".format(spotify_playlist['name']))
        return

    task_description = "Searching Tidal for {}/{} tracks in Spotify playlist '{}'".format(len(spotify_tracks) - cache_hits, len(spotify_tracks), spotify_playlist['name'])
    new_tidal_tracks = call_async_with_progress(tidal_search, spotify_track_mappings, task_description, config.get('subprocesses', 25), tidal_session=tidal_session)
    for index, tidal_track_id in enumerate(new_tidal_tracks):
        spotify_track = spotify_tracks[index]
        if tidal_track_id:
            new_tidal_track_ids.append(tidal_track_id)
            track_match_cache.insert((spotify_track['id'], tidal_track_id))
        else:
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find track {}: {} - {}".format(spotify_track['id'], ",".join([a['name'] for a in spotify_track['artists']]), spotify_track['name']) + color[1])

    if tidal_playlist_is_dirty(old_tidal_tracks, new_tidal_track_ids):
        set_tidal_playlist(tidal_playlist, new_tidal_track_ids)
    else:
        print("No changes to write to Tidal playlist")

def sync_list(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, playlists, config):
  for spotify_playlist, tidal_playlist in playlists:
    # sync the spotify playlist to tidal
    repeat_on_request_error(sync_playlist, spotify_session, tidal_session, spotify_playlist, tidal_playlist, config)

def pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists: Mapping[str, tidalapi.Playlist]):
    if spotify_playlist['name'] in tidal_playlists:
      # if there's an existing tidal playlist with the name of the current playlist then use that
      tidal_playlist = tidal_playlists[spotify_playlist['name']]
      return (spotify_playlist, tidal_playlist)
    else:
      return (spotify_playlist, None)

def get_user_playlist_mappings(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
  results = []
  spotify_playlists = get_playlists_from_spotify(spotify_session, config)
  tidal_playlists = get_tidal_playlists_dict(tidal_session)
  for spotify_playlist in spotify_playlists:
      results.append( pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists) )
  return results

def get_playlists_from_spotify(spotify_session: spotipy.Spotify, config):
    # get all the user playlists from the Spotify account
    playlists = []
    with tqdm(total=1.0) as pbar:
      pbar.set_description("Loading Spotify playlists")
      spotify_results = spotify_session.user_playlists(config['spotify']['username'])
      total = spotify_results['total']
      exclude_list = set([x.split(':')[-1] for x in config.get('excluded_playlists', [])])
      while True:
          pbar.update(len(spotify_results['items'])/total)
          for spotify_playlist in spotify_results['items']:
              if spotify_playlist['owner']['id'] == config['spotify']['username'] and not spotify_playlist['id'] in exclude_list:
                  playlists.append(spotify_playlist)
          # move to the next page of results if there are still playlists remaining
          if spotify_results['next']:
              spotify_results = spotify_session.next(spotify_results)
          else:
              break
    return playlists

def get_playlists_from_config(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    # get the list of playlist sync mappings from the configuration file
    def get_playlist_ids(config):
        return [(item['spotify_id'], item['tidal_id']) for item in config['sync_playlists']]
    output = []
    for spotify_id, tidal_id in get_playlist_ids(config):
        try:
            spotify_playlist = spotify_session.playlist(spotify_id)
        except spotipy.SpotifyException as e:
            print("Error getting Spotify playlist " + spotify_id)
            raise e
        try:
            tidal_playlist = tidal_session.playlist(tidal_id)
        except Exception as e:
            print("Error getting Tidal playlist " + tidal_id)
            raise e
        output.append((spotify_playlist, tidal_playlist))
    return output

