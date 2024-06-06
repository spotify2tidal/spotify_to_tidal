#!/usr/bin/env python3

import asyncio
from .cache import failure_cache, track_match_cache
from functools import partial
from typing import Callable, List, Sequence, Set, Mapping
import math
import requests
import sys
import spotipy
import tidalapi
from .tidalapi_patch import add_multiple_tracks_to_playlist, set_tidal_playlist
import time
from tqdm.asyncio import tqdm as atqdm
import traceback
import unicodedata
import math

from .type import spotify as t_spotify

def normalize(s) -> str:
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')

def simple(input_string: str) -> str:
    # only take the first part of a string before any hyphens or brackets to account for different versions
    return input_string.split('-')[0].strip().split('(')[0].strip().split('[')[0].strip()

def isrc_match(tidal_track: tidalapi.Track, spotify_track) -> bool:
    if "isrc" in spotify_track["external_ids"]:
        return tidal_track.isrc == spotify_track["external_ids"]["isrc"]
    return False

def duration_match(tidal_track: tidalapi.Track, spotify_track, tolerance=2) -> bool:
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

def artist_match(tidal_track: tidalapi.Track, spotify_track) -> bool:
    def split_artist_name(artist: str) -> Sequence[str]:
       if '&' in artist:
           return artist.split('&')
       elif ',' in artist:
           return artist.split(',')
       else:
           return [artist]

    def get_tidal_artists(tidal_track: tidalapi.Track, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in tidal_track.artists:
            if do_normalize:
                artist_name = normalize(artist.name)
            else:
                artist_name = artist.name
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip().lower()) for x in result])

    def get_spotify_artists(spotify_track: t_spotify.SpotifyTrack, do_normalize=False) -> Set[str]:
        result: list[str] = []
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
    if not spotify_track['id']: return False
    return isrc_match(tidal_track, spotify_track) or (
        duration_match(tidal_track, spotify_track)
        and name_match(tidal_track, spotify_track)
        and artist_match(tidal_track, spotify_track)
    )

async def tidal_search(spotify_track, rate_limiter, tidal_session: tidalapi.Session) -> tidalapi.Track | None:
    def _search_for_track_in_album():
        # search for album name and first album artist
        if 'album' in spotify_track and 'artists' in spotify_track['album'] and len(spotify_track['album']['artists']):
            album_result = tidal_session.search(simple(spotify_track['album']['name']) + " " + simple(spotify_track['album']['artists'][0]['name']), models=[tidalapi.album.Album])
            for album in album_result['albums']:
                album_tracks = album.tracks()
                if len(album_tracks) >= spotify_track['track_number']:
                    track = album_tracks[spotify_track['track_number'] - 1]
                    if match(track, spotify_track):
                        failure_cache.remove_match_failure(spotify_track['id'])
                        return track
    def _search_for_standalone_track():
        # if album search fails then search for track name and first artist
        for track in tidal_session.search(simple(spotify_track['name']) + ' ' + simple(spotify_track['artists'][0]['name']), models=[tidalapi.media.Track])['tracks']:
            if match(track, spotify_track):
                failure_cache.remove_match_failure(spotify_track['id'])
                return track
    await rate_limiter.acquire()
    album_search = await asyncio.to_thread( _search_for_track_in_album )
    if album_search:
        return album_search
    await rate_limiter.acquire()
    track_search = await asyncio.to_thread( _search_for_standalone_track )
    if track_search:
        return track_search
    return None

    # if none of the search modes succeeded then store the track id to the failure cache
    failure_cache.cache_match_failure(spotify_track['id'])

def get_tidal_playlists_dict(tidal_session: tidalapi.Session) -> Mapping[str, tidalapi.Playlist]:
    # a dictionary of name --> playlist
    print("Loading Tidal playlists... This may take some time.")
    tidal_playlists = tidal_session.user.playlists()
    output = {}
    for playlist in tidal_playlists:
        output[playlist.name] = playlist
    return output 

async def repeat_on_request_error(function, *args, remaining=5, **kwargs):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    try:
        return await function(*args, **kwargs)
    except (tidalapi.exceptions.TooManyRequests, requests.exceptions.RequestException) as e:
        if remaining:
            print(f"{str(e)} occurred, retrying {remaining} times")
        else:
            print(f"{str(e)} could not be recovered")

        if isinstance(e, requests.exceptions.RequestException) and not e.response is None:
            print(f"Response message: {e.response.text}")
            print(f"Response headers: {e.response.headers}")

        if not remaining:
            print("Aborting sync")
            print(f"The following arguments were provided:\n\n {str(args)}")
            print(traceback.format_exc())
            sys.exit(1)
        sleep_schedule = {5: 1, 4:10, 3:60, 2:5*60, 1:10*60} # sleep variable length of time depending on retry number
        time.sleep(sleep_schedule.get(remaining, 1))
        return await repeat_on_request_error(function, *args, remaining=remaining-1, **kwargs)


async def _fetch_all_from_spotify_in_chunks(spotify_session: spotipy.Spotify, fetch_function: Callable, reverse: bool = False) -> List[dict]:
    output = []
    print("Loading data from Spotify")
    results = fetch_function(0, spotify_session)
    output.extend([item['track'] for item in results['items'] if item['track'] is not None])

    # Get all the remaining tracks in parallel
    if results['next']:
        offsets = [results['limit'] * n for n in range(1, math.ceil(results['total'] / results['limit']))]
        extra_results = await asyncio.gather(
            *[asyncio.to_thread(fetch_function, offset, spotify_session) for offset in offsets]
        )
        for extra_result in extra_results:
            output.extend([item['track'] for item in extra_result['items'] if item['track'] is not None])
    
    if reverse:
        output.reverse()

    return output


async def get_tracks_from_spotify_playlist(spotify_session: spotipy.Spotify, spotify_playlist):
    def _get_tracks_from_spotify_playlist(offset: int, spotify_session: spotipy.Spotify, playlist_id: str):
        fields = "next,total,limit,items(track(name,album(name,artists),artists,track_number,duration_ms,id,external_ids(isrc)))"
        return spotify_session.playlist_tracks(playlist_id=playlist_id, fields=fields, offset=offset)

    print(f"Loading tracks from Spotify playlist '{spotify_playlist['name']}'")
    return await _fetch_all_from_spotify_in_chunks(spotify_session=spotify_session, fetch_function=lambda offset, session: _get_tracks_from_spotify_playlist(offset=offset, spotify_session=session, playlist_id=spotify_playlist["id"]))


async def get_tracks_from_spotify_favorites(spotify_session: spotipy.Spotify) -> List[dict]:
    def _get_favorite_tracks(offset: int, spotify_session: spotipy.Spotify):
        return spotify_session.current_user_saved_tracks(offset=offset)

    print("Loading favorite tracks from Spotify")
    return await _fetch_all_from_spotify_in_chunks(spotify_session=spotify_session, fetch_function=_get_favorite_tracks, reverse=True)


def populate_track_match_cache(spotify_tracks_: Sequence[t_spotify.SpotifyTrack], tidal_tracks_: Sequence[tidalapi.Track]):
    """ Populate the track match cache with all the existing tracks in Tidal playlist corresponding to Spotify playlist """
    def _populate_one_track_from_spotify(spotify_track: t_spotify.SpotifyTrack):
        for idx, tidal_track in list(enumerate(tidal_tracks)):
            if match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                tidal_tracks.pop(idx)
                return

    def _populate_one_track_from_tidal(tidal_track: tidalapi.Track):
        for idx, spotify_track in list(enumerate(spotify_tracks)):
            if match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                spotify_tracks.pop(idx)
                return

    # make a copy of the tracks to avoid modifying original arrays
    spotify_tracks = [t for t in spotify_tracks_]
    tidal_tracks = [t for t in tidal_tracks_]

    # first populate from the tidal tracks
    for track in tidal_tracks:
        _populate_one_track_from_tidal(track)
    # then populate from the subset of Spotify tracks that didn't match (to account for many-to-one style mappings)
    for track in spotify_tracks:
        _populate_one_track_from_spotify(track)

def get_new_tracks_from_spotify_playlist(spotify_tracks: Sequence[t_spotify.SpotifyTrack], old_tidal_tracks: Sequence[tidalapi.Track]) -> list[t_spotify.SpotifyTrack]:
    ''' Extracts only the new tracks in the Spotify playlist that are not already on Tidal or known match failures '''
    populate_track_match_cache(spotify_tracks, old_tidal_tracks)
    results = []
    for spotify_track in spotify_tracks:
        if not spotify_track['id']: continue
        if not track_match_cache.get(spotify_track['id']) and not failure_cache.has_match_failure(spotify_track['id']):
            results.append(spotify_track)
    return results

def get_tracks_for_new_tidal_playlist(spotify_tracks: Sequence[t_spotify.SpotifyTrack]) -> Sequence[int]:
    ''' gets list of corresponding tidal track ids for each spotify track, ignoring duplicates '''
    output = []
    seen_tracks = set()
    for spotify_track in spotify_tracks:
        if not spotify_track['id']: continue
        tidal_id = track_match_cache.get(spotify_track['id'])
        if tidal_id and not tidal_id in seen_tracks:
            output.append(tidal_id)
            seen_tracks.add(tidal_id)
    return output

async def sync_tracks(spotify_tracks: Sequence[t_spotify.SpotifyTrack], old_tidal_tracks: Sequence[tidalapi.Track], config, tidal_session: tidalapi.Session, tidal_playlist: tidalapi.UserPlaylist, sync_favorites: bool = False):
    async def _run_rate_limiter(semaphore):
        ''' Leaky bucket algorithm for rate limiting. Periodically releases an item from semaphore at rate_limit'''
        while True:
            await asyncio.sleep(delay=1/config.get('rate_limit', 12)) # sleep for min time between new function executions
            semaphore.release() # leak one item from the 'bucket'

    tracks_to_search: List[t_spotify.SpotifyTrack] = get_new_tracks_from_spotify_playlist(spotify_tracks=spotify_tracks, old_tidal_tracks=old_tidal_tracks)
    if not tracks_to_search:
        print("No new tracks to search in Spotify tracks")
        return

    # Search for each of the tracks on Tidal concurrently
    task_description = "Searching Tidal for {}/{} Spotify tracks".format(len(tracks_to_search), len(spotify_tracks))
    semaphore = asyncio.Semaphore(value=config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(coro=_run_rate_limiter(semaphore=semaphore))
    search_results = await atqdm.gather(
        *[repeat_on_request_error(tidal_search, t, semaphore, tidal_session) for t in tracks_to_search],
        desc=task_description
    )
    rate_limiter_task.cancel()

    # Add the search results to the cache
    for idx, spotify_track in enumerate(iterable=tracks_to_search):
        if search_results[idx]:
            track_match_cache.insert(mapping=(spotify_track['id'], search_results[idx].id))
        else:
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find track {}: {} - {}".format(spotify_track['id'], ",".join([a['name'] for a in spotify_track['artists']]), spotify_track['name']) + color[1])

    # Update the Tidal playlist or favorites if there are changes
    old_tidal_track_ids = [t.id for t in old_tidal_tracks]
    new_tidal_track_ids = get_tracks_for_new_tidal_playlist(spotify_tracks=spotify_tracks)
    if new_tidal_track_ids == old_tidal_track_ids:
        print("No changes to write to Tidal")
    elif new_tidal_track_ids[:len(old_tidal_track_ids)] == old_tidal_track_ids:
        # Append new tracks to the existing playlist or favorites if possible
        add_multiple_tracks_to_playlist(
            playlist=tidal_playlist,
            session=tidal_session,
            track_ids=new_tidal_track_ids[len(old_tidal_track_ids):], 
            sync_favorites=sync_favorites
        )
    else:
        # Erase old playlist or favorites and add new tracks from scratch if any reordering occured
        set_tidal_playlist(
            playlist=tidal_playlist,
            session=tidal_session,
            track_ids=new_tidal_track_ids, 
            sync_favorites=sync_favorites
        )

def sync_playlists_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, playlists, config):
    for spotify_playlist, tidal_playlist in playlists:
        asyncio.run(main=sync_playlist(spotify_session=spotify_session, tidal_session=tidal_session, spotify_playlist=spotify_playlist, tidal_playlist=tidal_playlist, config=config) )

async def sync_playlist(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_playlist, tidal_playlist: tidalapi.Playlist | None, config):
    # Create a new Tidal playlist if required
    if not tidal_playlist:
        print(f"No playlist found on Tidal corresponding to Spotify playlist: '{spotify_playlist['name']}', creating new playlist")
        tidal_playlist = tidal_session.user.create_playlist(spotify_playlist['name'], spotify_playlist['description'])

    spotify_tracks = await get_tracks_from_spotify_playlist(spotify_session=spotify_session, spotify_playlist=spotify_playlist)
    old_tidal_tracks = tidal_playlist.tracks()
    await sync_tracks(spotify_tracks=spotify_tracks, old_tidal_tracks=old_tidal_tracks, config=config, tidal_session=tidal_session, tidal_playlist=tidal_playlist)

def sync_favorites_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    asyncio.run(main=sync_favorites(spotify_session=spotify_session, tidal_session=tidal_session, config=config))

async def sync_favorites(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    spotify_tracks = await get_tracks_from_spotify_favorites(spotify_session=spotify_session)
    old_tidal_tracks = tidal_session.user.favorites.tracks()
    await sync_tracks(spotify_tracks=spotify_tracks, old_tidal_tracks=old_tidal_tracks, config=config, tidal_session=tidal_session, tidal_playlist=tidal_session.user.favorites, sync_favorites=True)

def pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists: Mapping[str, tidalapi.Playlist]):
    if spotify_playlist['name'] in tidal_playlists:
      # if there's an existing tidal playlist with the name of the current playlist then use that
      tidal_playlist = tidal_playlists[spotify_playlist['name']]
      return (spotify_playlist, tidal_playlist)
    else:
      return (spotify_playlist, None)

def get_user_playlist_mappings(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    results = []
    spotify_playlists = asyncio.run(get_playlists_from_spotify(spotify_session, config))
    tidal_playlists = get_tidal_playlists_dict(tidal_session)
    for spotify_playlist in spotify_playlists:
        results.append( pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists) )
    return results

async def get_playlists_from_spotify(spotify_session: spotipy.Spotify, config):
    # get all the user playlists from the Spotify account
    playlists = []
    print("Loading Spotify playlists")
    results = spotify_session.user_playlists(config['spotify']['username'])
    exclude_list = set([x.split(':')[-1] for x in config.get('excluded_playlists', [])])

    # get all the remaining playlists in parallel
    if results['next']:
        offsets = [ results['limit'] * n for n in range(1, math.ceil(results['total']/results['limit'])) ]
        extra_results = await atqdm.gather( *[asyncio.to_thread(spotify_session.user_playlists, config['spotify']['username'], offset=offset) for offset in offsets ] )
        for extra_result in extra_results:
            playlists.extend([p for p in extra_result['items'] if p['owner']['id'] == config['spotify']['username'] and not p['id'] in exclude_list])
    return playlists

def get_playlists_from_config(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    # get the list of playlist sync mappings from the configuration file
    def get_playlist_ids(config):
        return [(item['spotify_id'], item['tidal_id']) for item in config['sync_playlists']]
    output = []
    for spotify_id, tidal_id in get_playlist_ids(config=config):
        try:
            spotify_playlist = spotify_session.playlist(playlist_id=spotify_id)
        except spotipy.SpotifyException as e:
            print(f"Error getting Spotify playlist {spotify_id}")
            raise e
        try:
            tidal_playlist = tidal_session.playlist(playlist_id=tidal_id)
        except Exception as e:
            print(f"Error getting Tidal playlist {tidal_id}")
            raise e
        output.append((spotify_playlist, tidal_playlist))
    return output

