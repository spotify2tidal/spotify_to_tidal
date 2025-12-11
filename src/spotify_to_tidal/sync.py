#!/usr/bin/env python3

import asyncio
from .cache import failure_cache, track_match_cache, album_match_cache, artist_match_cache
import datetime
from difflib import SequenceMatcher
from functools import partial
from typing import Callable, List, Sequence, Set, Mapping
import math
import requests
import sys
import spotipy
import tidalapi
from .tidalapi_patch import add_multiple_tracks_to_playlist, clear_tidal_playlist, get_all_favorites, get_all_playlists, get_all_playlist_tracks, get_all_saved_albums, add_album_to_tidal_collection, get_all_saved_artists, add_artist_to_tidal_collection
import time
from tqdm.asyncio import tqdm as atqdm
from tqdm import tqdm
import traceback
import unicodedata
import math

from .type import spotify as t_spotify

def normalize(s) -> str:
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii')

def simple(input_string: str) -> list[str]:
    """
    Simple progressive text normalization for matching across platforms.
    Returns two variations: exact (normalized) and simplified (without parentheses).
    
    Args:
        input_string: Text to simplify
    
    Returns:
        List with [exact_normalized, simplified] versions
    """
    if not input_string:
        return [""]
    
    text = input_string.strip()
    
    # Exact: just normalize whitespace and dashes
    exact = ' '.join(text.split()).replace('–', '-').replace('—', '-').replace('−', '-')
    
    # Simplified: remove everything in parentheses/brackets
    simplified = text.split('(')[0].split('[')[0].strip()
    simplified = ' '.join(simplified.split()).replace('–', '-').replace('—', '-').replace('−', '-')
    
    # Return both variations, avoiding duplicates
    if exact == simplified:
        return [exact]
    else:
        return [exact, simplified]

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
    simple_spotify_track = simple(spotify_track['name'])[0].lower().split('feat.')[0].strip()
    return simple_spotify_track in tidal_track.name.lower() or normalize(simple_spotify_track) in normalize(tidal_track.name.lower())

def artist_match(tidal: tidalapi.Track | tidalapi.Album, spotify) -> bool:
    def split_artist_name(artist: str) -> Sequence[str]:
       if '&' in artist:
           return artist.split('&')
       elif ',' in artist:
           return artist.split(',')
       elif ' and ' in artist.lower():
           return artist.lower().split(' and ')
       else:
           return [artist]

    def get_tidal_artists(tidal: tidalapi.Track | tidalapi.Album, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in tidal.artists:
            if do_normalize:
                artist_name = normalize(artist.name)
            else:
                artist_name = artist.name
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip())[0].lower() for x in result])

    def get_spotify_artists(spotify, do_normalize=False) -> Set[str]:
        result: list[str] = []
        for artist in spotify['artists']:
            if do_normalize:
                artist_name = normalize(artist['name'])
            else:
                artist_name = artist['name']
            result.extend(split_artist_name(artist_name))
        return set([simple(x.strip())[0].lower() for x in result])
    # There must be at least one overlapping artist between the Tidal and Spotify track
    # Try with both un-normalized and then normalized
    if get_tidal_artists(tidal).intersection(get_spotify_artists(spotify)) != set():
        return True
    return get_tidal_artists(tidal, True).intersection(get_spotify_artists(spotify, True)) != set()

def match(tidal_track, spotify_track) -> bool:
    if not spotify_track['id']: return False
    return isrc_match(tidal_track, spotify_track) or (
        duration_match(tidal_track, spotify_track)
        and name_match(tidal_track, spotify_track)
        and artist_match(tidal_track, spotify_track)
    )

def test_album_similarity(spotify_album, tidal_album, threshold=0.6):
    spotify_simple = simple(spotify_album['name'])[0]
    tidal_simple = simple(tidal_album.name)[0]
    return SequenceMatcher(None, spotify_simple, tidal_simple).ratio() >= threshold and artist_match(tidal_album, spotify_album)

async def tidal_search(spotify_track, rate_limiter, tidal_session: tidalapi.Session) -> tidalapi.Track | None:
    def _search_for_track_in_album():
        # search for album name and first album artist
        if 'album' in spotify_track and 'artists' in spotify_track['album'] and len(spotify_track['album']['artists']):
            album_simple = simple(spotify_track['album']['name'])[0]
            artist_simple = simple(spotify_track['album']['artists'][0]['name'])[0]
            query = f"{album_simple} {artist_simple}"
            album_result = tidal_session.search(query, models=[tidalapi.album.Album])
            for album in album_result['albums']:
                if album.num_tracks >= spotify_track['track_number'] and test_album_similarity(spotify_track['album'], album):
                    album_tracks = album.tracks()
                    if len(album_tracks) < spotify_track['track_number']:
                        assert( not len(album_tracks) == album.num_tracks ) # incorrect metadata :(
                        continue
                    track = album_tracks[spotify_track['track_number'] - 1]
                    if match(track, spotify_track):
                        failure_cache.remove_match_failure(spotify_track['id'])
                        return track

    def _search_for_standalone_track():
        # if album search fails then search for track name and first artist
        track_simple = simple(spotify_track['name'])[0]
        artist_simple = simple(spotify_track['artists'][0]['name'])[0]
        query = f"{track_simple} {artist_simple}"
        for track in tidal_session.search(query, models=[tidalapi.media.Track])['tracks']:
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

    # if none of the search modes succeeded then store the track id to the failure cache
    failure_cache.cache_match_failure(spotify_track['id'])

async def repeat_on_request_error(function, *args, remaining=5, **kwargs):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    try:
        return await function(*args, **kwargs)
    except (tidalapi.exceptions.TooManyRequests, requests.exceptions.RequestException, spotipy.exceptions.SpotifyException) as e:
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


async def _fetch_all_from_spotify_in_chunks(fetch_function: Callable) -> List[dict]:
    output = []
    results = fetch_function(0)
    output.extend([item['track'] for item in results['items'] if item['track'] is not None])

    # Get all the remaining tracks in parallel
    if results['next']:
        offsets = [results['limit'] * n for n in range(1, math.ceil(results['total'] / results['limit']))]
        extra_results = await atqdm.gather(
            *[asyncio.to_thread(fetch_function, offset) for offset in offsets],
            desc="Fetching additional data chunks"
        )
        for extra_result in extra_results:
            output.extend([item['track'] for item in extra_result['items'] if item['track'] is not None])

    return output


async def get_tracks_from_spotify_playlist(spotify_session: spotipy.Spotify, spotify_playlist):
    def _get_tracks_from_spotify_playlist(offset: int, playlist_id: str):
        fields = "next,total,limit,items(track(name,album(name,artists),artists,track_number,duration_ms,id,external_ids(isrc))),type"
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

def populate_track_match_cache(spotify_tracks_: Sequence[t_spotify.SpotifyTrack], tidal_tracks_: Sequence[tidalapi.Track]):
    """ Populate the track match cache with all the existing tracks in Tidal playlist corresponding to Spotify playlist """
    def _populate_one_track_from_spotify(spotify_track: t_spotify.SpotifyTrack):
        for idx, tidal_track in list(enumerate(tidal_tracks)):
            if tidal_track.available and match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                tidal_tracks.pop(idx)
                return

    def _populate_one_track_from_tidal(tidal_track: tidalapi.Track):
        for idx, spotify_track in list(enumerate(spotify_tracks)):
            if tidal_track.available and match(tidal_track, spotify_track):
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

def get_new_spotify_tracks(spotify_tracks: Sequence[t_spotify.SpotifyTrack]) -> List[t_spotify.SpotifyTrack]:
    ''' Extracts only the tracks that have not already been seen in our Tidal caches '''
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
        if tidal_id:
            if tidal_id in seen_tracks:
                track_name = spotify_track['name']
                artist_names = ', '.join([artist['name'] for artist in spotify_track['artists']])
                print(f'Duplicate found: Track "{track_name}" by {artist_names} will be ignored') 
            else:
                output.append(tidal_id)
                seen_tracks.add(tidal_id)
    return output

async def search_new_tracks_on_tidal(tidal_session: tidalapi.Session, spotify_tracks: Sequence[t_spotify.SpotifyTrack], playlist_name: str, config: dict):
    """ Generic function for searching for each item in a list of Spotify tracks which have not already been seen and adding them to the cache """
    async def _run_rate_limiter(semaphore):
        ''' Leaky bucket algorithm for rate limiting. Periodically releases items from semaphore at rate_limit'''
        _sleep_time = config.get('max_concurrency', 10)/config.get('rate_limit', 10)/4 # aim to sleep approx time to drain 1/4 of 'bucket'
        t0 = datetime.datetime.now()
        while True:
            await asyncio.sleep(_sleep_time)
            t = datetime.datetime.now()
            dt = (t - t0).total_seconds()
            new_items = round(config.get('rate_limit', 10)*dt)
            t0 = t
            [semaphore.release() for _ in range(new_items)] # leak new_items from the 'bucket'

    # Extract the new tracks that do not already exist in the old tidal tracklist
    tracks_to_search = get_new_spotify_tracks(spotify_tracks)
    if not tracks_to_search:
        return

    # Search for each of the tracks on Tidal concurrently
    task_description = "Searching Tidal for {}/{} tracks in Spotify playlist '{}'".format(len(tracks_to_search), len(spotify_tracks), playlist_name)
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore))
    search_results = await atqdm.gather( *[ repeat_on_request_error(tidal_search, t, semaphore, tidal_session) for t in tracks_to_search ], desc=task_description )
    rate_limiter_task.cancel()

    # Add the search results to the cache
    song404 = []
    for idx, spotify_track in enumerate(tracks_to_search):
        if search_results[idx]:
            track_match_cache.insert( (spotify_track['id'], search_results[idx].id) )
        else:
            song404.append(f"{spotify_track['id']}: {','.join([a['name'] for a in spotify_track['artists']])} - {spotify_track['name']}")
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find the track " + song404[-1] + color[1])
    file_name = "songs not found.txt"
    header = f"==========================\nPlaylist: {playlist_name}\n==========================\n"
    with open(file_name, "a", encoding="utf-8") as file:
        file.write(header)
        for song in song404:
            file.write(f"{song}\n")

            
async def sync_playlist(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_playlist, tidal_playlist: tidalapi.Playlist | None, config: dict):
    """ sync given playlist to tidal """
    # Get the tracks from both Spotify and Tidal, creating a new Tidal playlist if necessary
    spotify_tracks = await get_tracks_from_spotify_playlist(spotify_session, spotify_playlist)
    if len(spotify_tracks) == 0:
        return # nothing to do
    if tidal_playlist:
        old_tidal_tracks = await get_all_playlist_tracks(tidal_playlist)
    else:
        print(f"No playlist found on Tidal corresponding to Spotify playlist: '{spotify_playlist['name']}', creating new playlist")
        tidal_playlist =  tidal_session.user.create_playlist(spotify_playlist['name'], spotify_playlist['description'])
        old_tidal_tracks = []

    # Extract the new tracks from the playlist that we haven't already seen before
    populate_track_match_cache(spotify_tracks, old_tidal_tracks)
    await search_new_tracks_on_tidal(tidal_session, spotify_tracks, spotify_playlist['name'], config)
    new_tidal_track_ids = get_tracks_for_new_tidal_playlist(spotify_tracks)

    # Update the Tidal playlist if there are changes
    old_tidal_track_ids = [t.id for t in old_tidal_tracks]
    if new_tidal_track_ids == old_tidal_track_ids:
        print("No changes to write to Tidal playlist")
    elif new_tidal_track_ids[:len(old_tidal_track_ids)] == old_tidal_track_ids:
        # Append new tracks to the existing playlist if possible
        add_multiple_tracks_to_playlist(tidal_playlist, new_tidal_track_ids[len(old_tidal_track_ids):])
    else:
        # Erase old playlist and add new tracks from scratch if any reordering occured
        clear_tidal_playlist(tidal_playlist)
        add_multiple_tracks_to_playlist(tidal_playlist, new_tidal_track_ids)

async def sync_favorites(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ sync user favorites to tidal """
    async def get_tracks_from_spotify_favorites() -> List[dict]:
        _get_favorite_tracks = lambda offset: spotify_session.current_user_saved_tracks(offset=offset)    
        tracks = await repeat_on_request_error( _fetch_all_from_spotify_in_chunks, _get_favorite_tracks)
        tracks.reverse()
        return tracks

    def get_new_tidal_favorites() -> List[int]:
        existing_favorite_ids = set([track.id for track in old_tidal_tracks])
        new_ids = []
        for spotify_track in spotify_tracks:
            match_id = track_match_cache.get(spotify_track['id'])
            if match_id and not match_id in existing_favorite_ids:
                new_ids.append(match_id)
        return new_ids

    print("Loading favorite tracks from Spotify")
    spotify_tracks = await get_tracks_from_spotify_favorites()
    print("Loading existing favorite tracks from Tidal")
    old_tidal_tracks = await get_all_favorites(tidal_session.user.favorites, order='DATE')
    populate_track_match_cache(spotify_tracks, old_tidal_tracks)
    await search_new_tracks_on_tidal(tidal_session, spotify_tracks, "Favorites", config)
    new_tidal_favorite_ids = get_new_tidal_favorites()
    if new_tidal_favorite_ids:
        for tidal_id in tqdm(new_tidal_favorite_ids, desc="Adding new tracks to Tidal favorites"):
            tidal_session.user.favorites.add_track(tidal_id)
    else:
        print("No new tracks to add to Tidal favorites")

def sync_playlists_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, playlists, config: dict):
  for spotify_playlist, tidal_playlist in playlists:
    # sync the spotify playlist to tidal
    asyncio.run(sync_playlist(spotify_session, tidal_session, spotify_playlist, tidal_playlist, config) )

def sync_favorites_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    asyncio.run(main=sync_favorites(spotify_session=spotify_session, tidal_session=tidal_session, config=config))

async def sync_albums(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ sync saved albums from Spotify to Tidal """
    async def get_albums_from_spotify_saved() -> List[dict]:
        async def _fetch_all_albums_from_spotify_in_chunks(fetch_function: Callable) -> List[dict]:
            output = []
            results = fetch_function(0)
            output.extend([item['album'] for item in results['items'] if item['album'] is not None])

            # Get all the remaining albums in parallel
            if results['next']:
                offsets = [results['limit'] * n for n in range(1, math.ceil(results['total'] / results['limit']))]
                extra_results = await atqdm.gather(
                    *[asyncio.to_thread(fetch_function, offset) for offset in offsets],
                    desc="Fetching additional data chunks"
                )
                for extra_result in extra_results:
                    output.extend([item['album'] for item in extra_result['items'] if item['album'] is not None])

            return output

        _get_saved_albums = lambda offset: spotify_session.current_user_saved_albums(offset=offset)
        albums = await repeat_on_request_error(_fetch_all_albums_from_spotify_in_chunks, _get_saved_albums)
        albums.reverse() 
        return albums

    def get_new_tidal_albums() -> List[str]:
        existing_album_ids = set([album.id for album in old_tidal_albums])
        new_ids = []
        for spotify_album in spotify_albums:
            match_id = album_match_cache.get(spotify_album['id'])
            if match_id and not match_id in existing_album_ids:
                new_ids.append(match_id)
        return new_ids

    print("Loading saved albums from Spotify")
    spotify_albums = await get_albums_from_spotify_saved()
    print("Loading existing albums from Tidal")
    old_tidal_albums = await get_all_saved_albums(tidal_session.user)
    populate_album_match_cache(spotify_albums, old_tidal_albums, config)
    await search_new_albums_on_tidal(tidal_session, spotify_albums, config)
    new_tidal_album_ids = get_new_tidal_albums()
    
    if new_tidal_album_ids:
        for tidal_id in tqdm(new_tidal_album_ids, desc="Adding new albums to Tidal"):
            add_album_to_tidal_collection(tidal_session, tidal_id)
    else:
        print("No new albums to add to Tidal")

def album_match(tidal_album: tidalapi.Album, spotify_album: dict, config: dict = None) -> bool:
    """ Check if a Tidal album matches a Spotify album using progressive matching """
    
    # Get progressive simplifications for album names (preserve edition info)
    spotify_variations = simple(spotify_album['name'])
    tidal_variations = simple(tidal_album.name)
    
    fuzzy_threshold = config.get('fuzzy_name_threshold', 0.80) if config else 0.80
    
    # Try each combination of variations (strictest first)
    album_name_matches = False
    for spotify_name in spotify_variations:
        for tidal_name in tidal_variations:
            spotify_lower = spotify_name.lower()
            tidal_lower = tidal_name.lower()
            
            # Exact substring match
            if spotify_lower in tidal_lower or tidal_lower in spotify_lower:
                album_name_matches = True
                break
                
            # Unicode normalized match
            norm_spotify = normalize(spotify_lower)
            norm_tidal = normalize(tidal_lower)
            if norm_spotify in norm_tidal or norm_tidal in norm_spotify:
                album_name_matches = True
                break
                
            # Fuzzy matching (if enabled)
            if config and config.get('enable_fuzzy_matching', False):
                similarity = SequenceMatcher(None, spotify_lower, tidal_lower).ratio()
                norm_similarity = SequenceMatcher(None, norm_spotify, norm_tidal).ratio()
                
                if similarity >= fuzzy_threshold or norm_similarity >= fuzzy_threshold:
                    album_name_matches = True
                    break
        
        if album_name_matches:
            break
    
    if not album_name_matches:
        return False
    
    # Artist matching using progressive simplification
    def get_artists(album):
        """Extract artist names from an album"""
        if hasattr(album, 'artists'):  # Tidal album
            return [artist.name for artist in album.artists]
        else:  # Spotify album
            return [artist['name'] for artist in album['artists']]
    
    def split_artists(artist_names):
        """Split artist names on common separators"""
        result = []
        for artist_name in artist_names:
            if '&' in artist_name:
                result.extend(artist_name.split('&'))
            elif ',' in artist_name:
                result.extend(artist_name.split(','))
            elif ' and ' in artist_name.lower():
                result.extend([part for part in artist_name.lower().split(' and ')])
            else:
                result.append(artist_name)
        return [name.strip() for name in result]
    
    # Get all artist variations for both albums
    tidal_artists = split_artists(get_artists(tidal_album))
    spotify_artists = split_artists(get_artists(spotify_album))
    
    fuzzy_artist_threshold = config.get('fuzzy_artist_threshold', 0.75) if config else 0.75
    
    # Try progressive matching for artists
    for tidal_artist in tidal_artists:
        tidal_variations = simple(tidal_artist)
        
        for spotify_artist in spotify_artists:
            spotify_variations = simple(spotify_artist)
            
            # Try each combination of variations
            for tidal_var in tidal_variations:
                for spotify_var in spotify_variations:
                    tidal_lower = tidal_var.lower()
                    spotify_lower = spotify_var.lower()
                    
                    # Exact match
                    if tidal_lower == spotify_lower:
                        return True
                    
                    # Substring match
                    if tidal_lower in spotify_lower or spotify_lower in tidal_lower:
                        return True
                    
                    # Unicode normalized match
                    norm_tidal = normalize(tidal_lower)
                    norm_spotify = normalize(spotify_lower)
                    if norm_tidal == norm_spotify:
                        return True
                    
                    # Fuzzy matching
                    if config and config.get('enable_fuzzy_matching', False):
                        similarity = SequenceMatcher(None, tidal_lower, spotify_lower).ratio()
                        norm_similarity = SequenceMatcher(None, norm_tidal, norm_spotify).ratio()
                        
                        if similarity >= fuzzy_artist_threshold or norm_similarity >= fuzzy_artist_threshold:
                            return True
    
    return False

def artist_match(tidal_artist: tidalapi.Artist, spotify_artist: dict, config: dict = None) -> bool:
    """ Check if a Tidal artist matches a Spotify artist using progressive matching """
    
    # Get progressive simplifications for artist names
    spotify_variations = simple(spotify_artist['name'])
    tidal_variations = simple(tidal_artist.name)
    
    fuzzy_threshold = config.get('fuzzy_name_threshold', 0.85) if config else 0.85
    
    # Try each combination of variations (strictest first)
    for spotify_name in spotify_variations:
        for tidal_name in tidal_variations:
            spotify_lower = spotify_name.lower()
            tidal_lower = tidal_name.lower()
            
            # Exact match
            if spotify_lower == tidal_lower:
                return True
                
            # Exact substring match
            if spotify_lower in tidal_lower or tidal_lower in spotify_lower:
                return True
                
            # Unicode normalized match
            norm_spotify = normalize(spotify_lower)
            norm_tidal = normalize(tidal_lower)
            if norm_spotify == norm_tidal:
                return True
                
            if norm_spotify in norm_tidal or norm_tidal in norm_spotify:
                return True
                
            # Fuzzy matching (if enabled)
            if config and config.get('enable_fuzzy_matching', False):
                similarity = SequenceMatcher(None, spotify_lower, tidal_lower).ratio()
                norm_similarity = SequenceMatcher(None, norm_spotify, norm_tidal).ratio()
                
                if similarity >= fuzzy_threshold or norm_similarity >= fuzzy_threshold:
                    return True
    
    return False

def populate_album_match_cache(spotify_albums: Sequence[dict], tidal_albums: Sequence[tidalapi.Album], config: dict = None):
    """ 
    Populate the album match cache with existing albums.
    """
    # Track which albums have already been matched to avoid duplicates
    matched_spotify_ids = set()
    matched_tidal_ids = set()
    
    # First pass: match tidal albums to spotify albums
    for tidal_album in tidal_albums:
        if tidal_album.id in matched_tidal_ids:
            continue
        
        for spotify_album in spotify_albums:
            if spotify_album['id'] in matched_spotify_ids:
                continue
                
            if album_match(tidal_album, spotify_album, config):
                album_match_cache.insert((spotify_album['id'], tidal_album.id))
                matched_spotify_ids.add(spotify_album['id'])
                matched_tidal_ids.add(tidal_album.id)
                break
    
    # Second pass: match remaining spotify albums to remaining tidal albums
    for spotify_album in spotify_albums:
        if spotify_album['id'] in matched_spotify_ids:
            continue
            
        for tidal_album in tidal_albums:
            if tidal_album.id in matched_tidal_ids:
                continue
                
            if album_match(tidal_album, spotify_album, config):
                album_match_cache.insert((spotify_album['id'], tidal_album.id))
                matched_spotify_ids.add(spotify_album['id'])
                matched_tidal_ids.add(tidal_album.id)
                break

def populate_artist_match_cache(spotify_artists: Sequence[dict], tidal_artists: Sequence[tidalapi.Artist], config: dict = None):
    """ 
    Populate the artist match cache with existing artists.
    """
    # Track which artists have already been matched to avoid duplicates
    matched_spotify_ids = set()
    matched_tidal_ids = set()
    
    for tidal_artist in tidal_artists:
        if tidal_artist.id in matched_tidal_ids:
            continue
        
        for spotify_artist in spotify_artists:
            if spotify_artist['id'] in matched_spotify_ids:
                continue
                
            if artist_match(tidal_artist, spotify_artist, config):
                artist_match_cache.insert((spotify_artist['id'], tidal_artist.id))
                matched_spotify_ids.add(spotify_artist['id'])
                matched_tidal_ids.add(tidal_artist.id)
                break
    
    # Second pass: try remaining unmatched Spotify artists against unmatched Tidal artists
    for spotify_artist in spotify_artists:
        if spotify_artist['id'] in matched_spotify_ids:
            continue
            
        for tidal_artist in tidal_artists:
            if tidal_artist.id in matched_tidal_ids:
                continue
                
            if artist_match(tidal_artist, spotify_artist, config):
                artist_match_cache.insert((spotify_artist['id'], tidal_artist.id))
                matched_spotify_ids.add(spotify_artist['id'])
                matched_tidal_ids.add(tidal_artist.id)
                break

async def search_new_albums_on_tidal(tidal_session: tidalapi.Session, spotify_albums: Sequence[dict], config: dict):
    """ Search for Spotify albums on Tidal and cache the results """
    def get_new_spotify_albums(spotify_albums: Sequence[dict]) -> List[dict]:
        results = []
        for spotify_album in spotify_albums:
            if not spotify_album['id']: continue
            if not album_match_cache.get(spotify_album['id']):
                results.append(spotify_album)
        return results
    
    async def tidal_album_search(spotify_album, rate_limiter, tidal_session: tidalapi.Session) -> tidalapi.Album | None:
        if not ('artists' in spotify_album and len(spotify_album['artists'])):
            return None
            
        # Progressive search strategy - try stronger matches first, then loosen
        search_queries = []
        album_name = spotify_album['name']
        artist_name = spotify_album['artists'][0]['name']
        
        # Get progressive variations for both album and artist
        album_variations = simple(album_name)
        artist_variations = simple(artist_name)
        
        # Create search queries from combinations of variations
        for album_var in album_variations:
            for artist_var in artist_variations:
                # Full search (album + artist)
                search_queries.append(f"{album_var} {artist_var}")
                
                # Album + simplified artist (first part only)
                artist_first_part = artist_var.split('&')[0].strip().split(' and ')[0].strip()
                if artist_first_part != artist_var:
                    search_queries.append(f"{album_var} {artist_first_part}")
        
        # Album only search with the most simplified version
        if album_variations:
            search_queries.append(album_variations[-1])  # Most simplified version
        
        # Special case for apostrophes
        if "'" in album_name:
            no_apostrophe_album = simple(album_name.replace("'", ""))
            if no_apostrophe_album and artist_variations:
                search_queries.append(f"{no_apostrophe_album[0]} {artist_variations[0]}")
        
        # Remove duplicates while preserving order
        unique_queries = []
        seen = set()
        for query in search_queries:
            if query not in seen:
                unique_queries.append(query)
                seen.add(query)
        search_queries = unique_queries
        
        # Try each search query until we find a match
        for i, query in enumerate(search_queries):
            await rate_limiter.acquire()
            try:
                album_result = tidal_session.search(query, models=[tidalapi.album.Album])
                if album_result and 'albums' in album_result and len(album_result['albums']) > 0:
                    print(f"  Search query {i+1}/6 '{query}' found {len(album_result['albums'])} results")
                    for tidal_album in album_result['albums']:
                        if album_match(tidal_album, spotify_album, config):
                            print(f"  ✓ Match found using query: '{query}'")
                            return tidal_album
                else:
                    print(f"  Search query {i+1}/6 '{query}' found no results")
            except Exception as e:
                # Continue to next query if this one fails
                print(f"  Search query {i+1}/6 '{query}' failed: {e}")
                continue
        
        # 6. Last resort: search by artist name only and check all albums
        # This handles cases where Tidal search doesn't return albums that exist
        await rate_limiter.acquire()
        artist_simple = simple(artist_name)[-1]  # Most simplified
        print(f"  Final search: artist-only '{artist_simple}'")
        try:
            artist_result = tidal_session.search(artist_simple, models=[tidalapi.album.Album])
            if artist_result and 'albums' in artist_result:
                print(f"  Artist-only search found {len(artist_result['albums'])} albums")
                for tidal_album in artist_result['albums']:
                    if album_match(tidal_album, spotify_album, config):
                        print(f"  ✓ Match found using artist-only search")
                        return tidal_album
            else:
                print(f"  Artist-only search found no results")
        except Exception as e:
            print(f"  Artist-only search for '{artist_simple}' failed: {e}")
                
        return None
    
    # Rate limiter setup similar to track search
    async def _run_rate_limiter(semaphore):
        _sleep_time = config.get('max_concurrency', 10)/config.get('rate_limit', 10)/4
        t0 = datetime.datetime.now()
        while True:
            await asyncio.sleep(_sleep_time)
            t = datetime.datetime.now()
            dt = (t - t0).total_seconds()
            new_items = round(config.get('rate_limit', 10)*dt)
            t0 = t
            [semaphore.release() for _ in range(new_items)]

    albums_to_search = get_new_spotify_albums(spotify_albums)
    if not albums_to_search:
        return

    # Search for each album on Tidal concurrently
    task_description = f"Searching Tidal for {len(albums_to_search)}/{len(spotify_albums)} albums"
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore))
    search_results = await atqdm.gather(*[repeat_on_request_error(tidal_album_search, a, semaphore, tidal_session) for a in albums_to_search], desc=task_description)
    rate_limiter_task.cancel()

    # Add search results to cache
    albums_not_found = []
    for idx, spotify_album in enumerate(albums_to_search):
        if search_results[idx]:
            album_match_cache.insert((spotify_album['id'], search_results[idx].id))
        else:
            album_info = f"{spotify_album['id']}: {','.join([a['name'] for a in spotify_album['artists']])} - {spotify_album['name']}"
            albums_not_found.append(album_info)
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find album " + album_info + color[1])
    
    # Log albums not found
    if albums_not_found:
        file_name = "albums not found.txt"
        header = f"==========================\nSaved Albums Sync\n==========================\n"
        with open(file_name, "a", encoding="utf-8") as file:
            file.write(header)
            for album in albums_not_found:
                file.write(f"{album}\n")

async def sync_artists(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ sync followed artists from Spotify to Tidal """
    async def get_artists_from_spotify_followed() -> List[dict]:
        async def _fetch_all_artists_from_spotify_in_chunks(fetch_function: Callable) -> List[dict]:
            output = []
            results = fetch_function(limit=50)
            if results and 'artists' in results:
                output.extend([item for item in results['artists']['items'] if item is not None])
                
                # Handle pagination
                while results['artists']['next']:
                    after = results['artists']['cursors']['after']
                    results = fetch_function(limit=50, after=after)
                    if results and 'artists' in results:
                        output.extend([item for item in results['artists']['items'] if item is not None])
                    else:
                        break
            return output
            
        _get_followed_artists = lambda **kwargs: spotify_session.current_user_followed_artists(**kwargs)
        return await repeat_on_request_error(_fetch_all_artists_from_spotify_in_chunks, _get_followed_artists)

    def get_new_tidal_artists() -> List[str]:
        existing_artist_ids = set([artist.id for artist in old_tidal_artists])
        new_ids = []
        for spotify_artist in spotify_artists:
            match_id = artist_match_cache.get(spotify_artist['id'])
            if match_id and not match_id in existing_artist_ids:
                new_ids.append(match_id)
        return new_ids

    print("Loading followed artists from Spotify")
    spotify_artists = await get_artists_from_spotify_followed()
    print("Loading existing followed artists from Tidal")
    old_tidal_artists = await get_all_saved_artists(tidal_session.user)
    populate_artist_match_cache(spotify_artists, old_tidal_artists, config)
    await search_new_artists_on_tidal(tidal_session, spotify_artists, config)
    new_tidal_artist_ids = get_new_tidal_artists()
    if new_tidal_artist_ids:
        for tidal_id in tqdm(new_tidal_artist_ids, desc="Following new artists on Tidal"):
            add_artist_to_tidal_collection(tidal_session, tidal_id)
    else:
        print("No new artists to follow on Tidal")

async def search_new_artists_on_tidal(tidal_session: tidalapi.Session, spotify_artists: Sequence[dict], config: dict):
    """ Search for Spotify artists on Tidal and cache the results """
    def get_new_spotify_artists(spotify_artists: Sequence[dict]) -> List[dict]:
        results = []
        for spotify_artist in spotify_artists:
            if not spotify_artist['id']: continue
            if not artist_match_cache.get(spotify_artist['id']):
                results.append(spotify_artist)
        return results
    
    new_spotify_artists = get_new_spotify_artists(spotify_artists)
    
    if not new_spotify_artists:
        print("All Spotify artists are already matched in the cache")
        return

    async def tidal_artist_search(spotify_artist: dict, semaphore, tidal_session) -> tidalapi.Artist | None:
        query = spotify_artist['name']
        await semaphore.acquire()
        
        try:
            artist_results = tidal_session.search(query, models=[tidalapi.Artist])
            if artist_results and 'artists' in artist_results and len(artist_results['artists']) > 0:
                for tidal_artist in artist_results['artists']:
                    if artist_match(tidal_artist, spotify_artist, config):
                        return tidal_artist
            return None
        except Exception as e:
            print(f"  Search error for '{query}': {e}")
            return None
    
    async def _run_rate_limiter(semaphore):
        _sleep_time = config.get('max_concurrency', 10)/config.get('rate_limit', 10)/4
        t0 = datetime.datetime.now()
        while True:
            await asyncio.sleep(_sleep_time)
            t = datetime.datetime.now()
            dt = (t - t0).total_seconds()
            new_items = round(config.get('rate_limit', 10)*dt)
            t0 = t
            [semaphore.release() for _ in range(new_items)]

    # Search for each artist on Tidal concurrently
    task_description = f"Searching Tidal for {len(new_spotify_artists)}/{len(spotify_artists)} artists"
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore))
    search_results = await atqdm.gather(*[repeat_on_request_error(tidal_artist_search, a, semaphore, tidal_session) for a in new_spotify_artists], desc=task_description)
    rate_limiter_task.cancel()

    # Cache the results
    artists_not_found = []
    for idx, spotify_artist in enumerate(new_spotify_artists):
        if search_results[idx]:
            artist_match_cache.insert((spotify_artist['id'], search_results[idx].id))
        else:
            artists_not_found.append(f"{spotify_artist['name']}")

    if artists_not_found:
        with open("artists not found.txt", "w", encoding="utf-8") as f:
            for artist in artists_not_found:
                f.write(f"{artist}\n")
        print(f"Wrote {len(artists_not_found)} artists not found to 'artists not found.txt'")

def sync_albums_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    asyncio.run(sync_albums(spotify_session, tidal_session, config))

def sync_artists_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    asyncio.run(sync_artists(spotify_session, tidal_session, config))

def get_tidal_playlists_wrapper(tidal_session: tidalapi.Session) -> Mapping[str, tidalapi.Playlist]:
    tidal_playlists = asyncio.run(get_all_playlists(tidal_session.user))
    return {playlist.name: playlist for playlist in tidal_playlists}

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
    tidal_playlists = get_tidal_playlists_wrapper(tidal_session)
    for spotify_playlist in spotify_playlists:
        results.append( pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists) )
    return results

async def get_playlists_from_spotify(spotify_session: spotipy.Spotify, config):
    # get all the playlists from the Spotify account
    playlists = []
    print("Loading Spotify playlists")
    first_results = spotify_session.current_user_playlists()
    exclude_list = set([x.split(':')[-1] for x in config.get('excluded_playlists', [])])
    playlists.extend([p for p in first_results['items']])
    user_id = spotify_session.current_user()['id']

    # get all the remaining playlists in parallel
    if first_results['next']:
        offsets = [ first_results['limit'] * n for n in range(1, math.ceil(first_results['total']/first_results['limit'])) ]
        extra_results = await atqdm.gather( *[asyncio.to_thread(spotify_session.current_user_playlists, offset=offset) for offset in offsets ] )
        for extra_result in extra_results:
            playlists.extend([p for p in extra_result['items']])

    # filter out playlists that don't belong to us or are on the exclude list
    my_playlist_filter = lambda p: p and p['owner']['id'] == user_id
    exclude_filter = lambda p: not p['id'] in exclude_list
    return list(filter( exclude_filter, filter( my_playlist_filter, playlists )))

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

