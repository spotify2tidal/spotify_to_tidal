#!/usr/bin/env python3

# from . import *

import logging
import typing

from functools import partial
from multiprocessing import Pool
import requests
import sys
import spotipy
import tidalapi
import tidalapi.playlist
from .tidalapi_patch import set_tidal_playlist
from .filters import *
import time
from tqdm import tqdm
import traceback
import yaml

def tidal_search(spotify_track_and_cache, tidal_session: tidalapi.Session):
    spotify_track, cached_tidal_track = spotify_track_and_cache
    if cached_tidal_track: return cached_tidal_track
    # search for album name and first album artist
    if 'album' in spotify_track and 'artists' in spotify_track['album'] and len(spotify_track['album']['artists']):
        album_result = tidal_session.search(simple(spotify_track['album']['name']) + " " + simple(spotify_track['album']['artists'][0]['name']), models=[tidalapi.album.Album])
        for album in album_result['albums']:
            album_tracks = album.tracks()
            if len(album_tracks) >= spotify_track['track_number']:
                track = album_tracks[spotify_track['track_number'] - 1]
                if match(track, spotify_track):
                    return track
    # if that fails then search for track name and first artist
    search_res = tidal_session.search(simple(spotify_track['name']) + ' ' + simple(spotify_track['artists'][0]['name']), models=[tidalapi.media.Track])
    return next((x for x in search_res['tracks'] if match(x, spotify_track)), None)


def get_tidal_playlists_dict(tidal_session: tidalapi.Session) -> typing.Dict[str, TidalPlaylist]:
    # a dictionary of name --> playlist
    tidal_playlists = tidal_session.user.playlists()
    output = {}
    for playlist in tidal_playlists:
        output[playlist.name] = playlist
    return output 

def repeat_on_request_error(function: typing.Callable, *args, **kwargs):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    sleep_schedule = {5: 1, 4:10, 3:60, 2:5*60, 1:10*60} # sleep variable length of time depending on retry number
    for rem_attempts in range(5, 0, -1):
        try:
            return function(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            if rem_attempts > 0:
                logging.warning(f"{str(e)} occurred, retrying {rem_attempts} more times")
            else:
                logging.critical("%s could not be recovered", str(e))
                logging.debug("Exception info: %s", traceback.format_exception(e))

            if e.response is not None:
                logging.debug("Response message: %s", e.response.text)
                logging.debug("Response headers: %s", e.response.headers)
            time.sleep(sleep_schedule.get(rem_attempts, 1))
    
    logging.critical("Aborting sync")
    logging.critical("The following arguments were provided\n\n: %s", str(args))
    logging.exception(traceback.format_exc())
    sys.exit(1)

def _enumerate_wrapper(value_tuple: typing.Tuple, function: typing.Callable, **kwargs) -> typing.List:
    # just a wrapper which accepts a tuple from enumerate and returns the index back as the first argument
    index, value = value_tuple
    return (index, repeat_on_request_error(function, value, **kwargs))

def call_async_with_progress(function, values, description, num_processes, **kwargs):
    results = len(values)*[None]
    with Pool(processes=num_processes) as process_pool:
        for index, result in tqdm(process_pool.imap_unordered(partial(_enumerate_wrapper, function=function, **kwargs),
                                  enumerate(values)), total=len(values), desc=description):
            results[index] = result
    return results

def get_tracks_from_spotify_playlist(spotify_session: spotipy.Spotify, spotify_playlist) -> typing.List[SpotifyTrack]:
    output = []
    results: typing.List[SpotifyTrack] = spotify_session.playlist_tracks(
        spotify_playlist["id"],
        fields="next,items(track(name,album(name,artists),artists,track_number,duration_ms,id,external_ids(isrc)))",
    )
    while True:
        output.extend([r['track'] for r in results['items'] if r['track'] is not None])
        # move to the next page of results if there are still tracks remaining in the playlist
        if results['next']:
            results = spotify_session.next(results)
        else:
            return output

class TidalPlaylistCache:
    def __init__(self, playlist):
        self._data = playlist.tracks()

    def _search(self, spotify_track: SpotifyTrack):
        ''' check if the given spotify track was already in the tidal playlist.'''
        return next(filter(lambda x: match(x, spotify_track), self._data), None)

    def search(self, spotify_session: spotipy.Spotify, spotify_playlist):
        ''' Add the cached tidal track where applicable to a list of spotify tracks '''
        results = []
        cache_hits = 0
        work_to_do = False
        spotify_tracks = get_tracks_from_spotify_playlist(spotify_session, spotify_playlist)
        for track in spotify_tracks:
            cached_track = self._search(track)
            if cached_track:
                results.append( (track, cached_track) )
                cache_hits += 1
            else:
                results.append( (track, None) )
        return (results, cache_hits)

def tidal_playlist_is_dirty(playlist: TidalPlaylist, new_track_ids: List[TidalID]) -> bool:
    old_tracks = playlist.tracks()
    if len(old_tracks) != len(new_track_ids):
        return True
    for i in range(len(old_tracks)):
        if old_tracks[i].id != new_track_ids[i]:
            return True
    return False

def sync_playlist(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_id: SpotifyID, tidal_id: TidalID, config):
    try:
        spotify_playlist = spotify_session.playlist(spotify_id)
    except spotipy.SpotifyException as e:
        logging.error("Error getting Spotify playlist %s", spotify_id)
        logging.exception(e)
        return
    if tidal_id:
        # if a Tidal playlist was specified then look it up
        try:
            tidal_playlist = tidal_session.playlist(tidal_id)
        except Exception as e:
            logging.error("Error getting Tidal playlist " + tidal_id)
            logging.exception(e)
            return
    else:
        # create a new Tidal playlist if required
        logging.warn("No playlist found on Tidal corresponding to Spotify playlist: %s. Creating new playlist", spotify_playlist['name'])
        tidal_playlist =  tidal_session.user.create_playlist(spotify_playlist['name'], spotify_playlist['description'])
    tidal_track_ids = []
    spotify_tracks, cache_hits = TidalPlaylistCache(tidal_playlist).search(spotify_session, spotify_playlist)
    if cache_hits == len(spotify_tracks):
        logging.warn("No new tracks to search in Spotify playlist '%s'", spotify_playlist['name'])
        return

    task_description = "Searching Tidal for {}/{} tracks in Spotify playlist '{}'".format(len(spotify_tracks) - cache_hits, len(spotify_tracks), spotify_playlist['name'])
    tidal_tracks = call_async_with_progress(tidal_search, spotify_tracks, task_description, config.get('subprocesses', 50), tidal_session=tidal_session)
    for index, tidal_track in enumerate(tidal_tracks):
        spotify_track = spotify_tracks[index][0]
        if tidal_track:
            tidal_track_ids.append(tidal_track.id)
        else:
            color = ('\033[91m', '\033[0m')
            logging.warn(color[0] + "Could not find track %s: %s - %s" + color[1], spotify_track['id'], ",".join(map(lambda x: x['name'], spotify_track['artists'])), spotify_track['name'])

    if tidal_playlist_is_dirty(tidal_playlist, tidal_track_ids):
        set_tidal_playlist(tidal_playlist, tidal_track_ids)
    else:
        print("No changes to write to Tidal playlist")

def sync_list(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, playlists: typing.List[PlaylistConfig], config: SyncConfig):
  results = []
  for spotify_id, tidal_id in playlists:
    # sync the spotify playlist to tidal
    repeat_on_request_error(sync_playlist, spotify_session, tidal_session, spotify_id, tidal_id, config)
    results.append(tidal_id)
  return results

def pick_tidal_playlist_for_spotify_playlist(spotify_playlist: typing.Dict[str, typing.Any], tidal_playlists: TidalPlaylist) -> typing.Tuple[SpotifyID, typing.Optional[TidalID]]:
    if spotify_playlist['name'] in tidal_playlists:
      # if there's an existing tidal playlist with the name of the current playlist then use that
      tidal_playlist = tidal_playlists[spotify_playlist['name']]
      return (spotify_playlist['id'], tidal_playlist.id)
    else:
      return (spotify_playlist['id'], None)
    

def get_user_playlist_mappings(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: SyncConfig):
    results = []
    spotify_playlists = get_playlists_from_spotify(spotify_session, config)
    tidal_playlists = get_tidal_playlists_dict(tidal_session)
    for spotify_playlist in spotify_playlists:
        results.append( pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists) )
    return results

def get_playlists_from_spotify(spotify_session: spotipy.Spotify, config: SyncConfig):
    # get all the user playlists from the Spotify account
    playlists = []
    spotify_results = spotify_session.user_playlists(config['spotify']['username'])
    exclude_list = set(map(str.split(':')[-1], config.get('excluded_playlists', [])))
    while True:
        for spotify_playlist in spotify_results['items']:
            if spotify_playlist['owner']['id'] == config['spotify']['username'] and not spotify_playlist['id'] in exclude_list:
                playlists.append(spotify_playlist)
        # move to the next page of results if there are still playlists remaining
        if spotify_results['next']:
            spotify_results = spotify_session.next(spotify_results)
        else:
            break
    return playlists

def get_playlists_from_config(config: SyncConfig) -> typing.List[typing.Tuple[SpotifyID, TidalID]]:
    # get the list of playlist sync mappings from the configuration file
    return list(map(lambda x: (x['spotify_id'], x['tidal_id']), config.get('sync_playlists', [])))

