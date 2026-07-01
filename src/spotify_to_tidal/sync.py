#!/usr/bin/env python3

import asyncio
from typing import Callable, List, Optional, Sequence, Set, Mapping
import requests
import spotipy
import tidalapi
from tqdm.asyncio import tqdm as atqdm
from tqdm import tqdm

from .cache import failure_cache, track_match_cache, album_match_cache, artist_match_cache
from .tidalapi_patch import clear_tidal_playlist, add_tracks_to_tidal_playlist, get_all_favorites, get_all_playlists, get_all_playlist_tracks, get_all_saved_albums, add_album_to_tidal_collection, get_all_saved_artists, add_artist_to_tidal_collection
from .matching import (
    normalize, simple, isrc_match, duration_match, name_match, artists_overlap, match,
    test_album_similarity, _names_match, album_match, artist_match,
)
from .ratelimit import repeat_on_request_error, _run_rate_limiter
from .spotify_api import (
    _fetch_all_from_spotify_in_chunks, get_tracks_from_spotify_playlist,
    get_followed_artists_from_spotify, get_playlists_from_spotify,
)
from .type import spotify as t_spotify

# Not-found logging lives in logfile.py; re-exported here as sync's matching code
# records unmatched tracks/albums/artists via add_not_found_item.
from .logfile import _not_found_items, add_not_found_item, write_not_found_log, clear_not_found_log

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

async def _add_items_to_tidal(tidal_ids: Sequence, desc: str, add_fn: Callable, item_type: str):
    """ Add each Tidal id via add_fn(tidal_id), retrying transient errors. A single bad/unavailable id
        (e.g. a 404) is logged and skipped rather than aborting the whole batch. """
    async def _add(tidal_id):
        return await asyncio.to_thread(add_fn, tidal_id)
    for tidal_id in tqdm(tidal_ids, desc=desc):
        try:
            await repeat_on_request_error(_add, tidal_id)
        except (requests.exceptions.RequestException, spotipy.exceptions.SpotifyException) as e:
            add_not_found_item(item_type, f"Failed to add Tidal {item_type} {tidal_id}: {e}")


def populate_track_match_cache(spotify_tracks_: Sequence[t_spotify.SpotifyTrack], tidal_tracks_: Sequence[tidalapi.Track], config: Optional[dict] = None):
    """ Populate the track match cache with all the existing tracks in Tidal playlist corresponding to Spotify playlist """
    def _populate_one_track_from_spotify(spotify_track: t_spotify.SpotifyTrack):
        for idx, tidal_track in list(enumerate(tidal_tracks)):
            if tidal_track.available and match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                record_artist_matches_from_release(spotify_track, tidal_track, config)
                tidal_tracks.pop(idx)
                return

    def _populate_one_track_from_tidal(tidal_track: tidalapi.Track):
        for idx, spotify_track in list(enumerate(spotify_tracks)):
            if tidal_track.available and match(tidal_track, spotify_track):
                track_match_cache.insert((spotify_track['id'], tidal_track.id))
                record_artist_matches_from_release(spotify_track, tidal_track, config)
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
    # Extract the new tracks that do not already exist in the old tidal tracklist
    tracks_to_search = get_new_spotify_tracks(spotify_tracks)
    if not tracks_to_search:
        return

    # Search for each of the tracks on Tidal concurrently
    task_description = "Searching Tidal for {}/{} tracks in Spotify playlist '{}'".format(len(tracks_to_search), len(spotify_tracks), playlist_name)
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore, config))
    # Isolate each search so one track's non-retryable error doesn't abort the whole batch (atqdm.gather
    # has no return_exceptions; capture per task and let the loop below treat exceptions as a miss).
    async def _search_one(spotify_track):
        try:
            return await repeat_on_request_error(tidal_search, spotify_track, semaphore, tidal_session)
        except Exception as e:
            return e
    search_results = await atqdm.gather( *[ _search_one(t) for t in tracks_to_search ], desc=task_description )
    rate_limiter_task.cancel()

    # Add the search results to the cache
    for idx, spotify_track in enumerate(tracks_to_search):
        result = search_results[idx]
        if isinstance(result, Exception):
            print(f"Error searching for track {spotify_track['id']}: {result}")
            result = None
        if result:
            track_match_cache.insert( (spotify_track['id'], result.id) )
            record_artist_matches_from_release(spotify_track, result, config)
        else:
            song_info = f"{spotify_track['id']}: {','.join([a['name'] for a in spotify_track['artists']])} - {spotify_track['name']}"
            add_not_found_item('track', song_info, playlist_name)
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find the track " + song_info + color[1])


async def sync_playlist(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_playlist, tidal_playlist: tidalapi.Playlist | None, config: dict):
    """ sync given playlist to tidal """
    # Get the tracks from both Spotify and Tidal, creating a new Tidal playlist if necessary
    spotify_tracks = await get_tracks_from_spotify_playlist(spotify_session, spotify_playlist)
    if len(spotify_tracks) == 0:
        return # nothing to do
    if tidal_playlist:
        old_tidal_tracks = await repeat_on_request_error(get_all_playlist_tracks, tidal_playlist)
    else:
        print(f"No playlist found on Tidal corresponding to Spotify playlist: '{spotify_playlist['name']}', creating new playlist")
        tidal_playlist = await repeat_on_request_error(asyncio.to_thread, tidal_session.user.create_playlist, spotify_playlist['name'], spotify_playlist['description'])
        old_tidal_tracks = []

    # Extract the new tracks from the playlist that we haven't already seen before
    populate_track_match_cache(spotify_tracks, old_tidal_tracks, config)
    await search_new_tracks_on_tidal(tidal_session, spotify_tracks, spotify_playlist['name'], config)
    new_tidal_track_ids = get_tracks_for_new_tidal_playlist(spotify_tracks)

    # Update the Tidal playlist if there are changes
    old_tidal_track_ids = [t.id for t in old_tidal_tracks]
    if new_tidal_track_ids == old_tidal_track_ids:
        print("No changes to write to Tidal playlist")
    elif new_tidal_track_ids[:len(old_tidal_track_ids)] == old_tidal_track_ids:
        # Append new tracks to the existing playlist if possible
        await add_tracks_to_tidal_playlist(tidal_playlist, new_tidal_track_ids[len(old_tidal_track_ids):])
    else:
        # Erase old playlist and add new tracks from scratch if any reordering occured
        await clear_tidal_playlist(tidal_playlist)
        await add_tracks_to_tidal_playlist(tidal_playlist, new_tidal_track_ids)

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
    old_tidal_tracks = await repeat_on_request_error(get_all_favorites, tidal_session.user.favorites, order='DATE')
    populate_track_match_cache(spotify_tracks, old_tidal_tracks, config)
    await search_new_tracks_on_tidal(tidal_session, spotify_tracks, "Favorites", config)
    new_tidal_favorite_ids = get_new_tidal_favorites()
    if new_tidal_favorite_ids:
        await _add_items_to_tidal(new_tidal_favorite_ids, "Adding new tracks to Tidal favorites",
                                  tidal_session.user.favorites.add_track, 'track')
    else:
        print("No new tracks to add to Tidal favorites")

def sync_playlists_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, playlists, config: dict):
  for spotify_playlist, tidal_playlist in playlists:
    # sync the spotify playlist to tidal; a failure on one playlist shouldn't abort the rest
    try:
        asyncio.run(sync_playlist(spotify_session, tidal_session, spotify_playlist, tidal_playlist, config) )
    except (requests.exceptions.RequestException, spotipy.exceptions.SpotifyException) as e:
        print(f"Error syncing playlist '{spotify_playlist['name']}': {e}; skipping to next playlist")

def sync_favorites_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config):
    asyncio.run(main=sync_favorites(spotify_session=spotify_session, tidal_session=tidal_session, config=config))

async def sync_albums(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ sync saved albums from Spotify to Tidal """
    async def get_albums_from_spotify_saved() -> List[dict]:
        _get_saved_albums = lambda offset: spotify_session.current_user_saved_albums(offset=offset)
        albums = await repeat_on_request_error(_fetch_all_from_spotify_in_chunks, _get_saved_albums, item_key="album")
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
    old_tidal_albums = await repeat_on_request_error(get_all_saved_albums, tidal_session.user)
    populate_album_match_cache(spotify_albums, old_tidal_albums, config)
    await search_new_albums_on_tidal(tidal_session, spotify_albums, config)
    new_tidal_album_ids = get_new_tidal_albums()
    
    if new_tidal_album_ids:
        await _add_items_to_tidal(new_tidal_album_ids, "Adding new albums to Tidal",
                                  lambda tid: add_album_to_tidal_collection(tidal_session, tid), 'album')
    else:
        print("No new albums to add to Tidal")

# Spotify artist ids we still need a Tidal id for (followed on Spotify, not already followed on
# Tidal). Empty unless artist sync is active, so the release harvest below is a no-op otherwise.
_wanted_artist_ids: Set[str] = set()

def set_wanted_artist_ids(ids: Set[str]):
    global _wanted_artist_ids
    _wanted_artist_ids = set(ids)

def record_artist_matches_from_release(spotify_release: dict, tidal_release, config: Optional[dict] = None):
    """ Derive Spotify -> Tidal artist ID mappings from an already-matched release (track/album).

    Because the release itself was matched — ideally by ISRC for tracks — the Tidal artists credited
    on it are the correct counterparts of the release's Spotify artists. This resolves a followed
    artist's Tidal ID directly from real content and disambiguates same-named artists far more
    reliably than a bare artist-name search. Only artists in the `wanted` set are recorded, so a
    multi-artist release contributes at most the followed artists we still need. """
    if not _wanted_artist_ids:
        return
    tidal_artists = getattr(tidal_release, 'artists', None)
    if not isinstance(tidal_artists, (list, tuple)) or not tidal_artists:
        return
    for spotify_artist in spotify_release.get('artists') or []:
        spotify_id = spotify_artist.get('id')
        if not spotify_id or spotify_id not in _wanted_artist_ids or artist_match_cache.get(spotify_id):
            continue
        for tidal_artist in tidal_artists:
            tidal_id = getattr(tidal_artist, 'id', None)
            if tidal_id is None:
                continue
            if _names_match(spotify_artist.get('name', ''), getattr(tidal_artist, 'name', '') or '', config):
                artist_match_cache.insert((spotify_id, tidal_id))
                break

def _populate_match_cache(spotify_items: Sequence[dict], tidal_items: Sequence, cache, match_fn: Callable, config: Optional[dict] = None, on_match: Optional[Callable] = None):
    """ Two-pass match of Spotify items against Tidal items, inserting matches into the given cache.
        First pass iterates Tidal items; second pass retries any unmatched Spotify items.
        Each side is matched at most once to avoid duplicate mappings. Mappings already present in
        the cache (e.g. artist ids harvested from synced releases) are honored and never overwritten.
        on_match(spotify_item, tidal_item), if given, is called for each newly matched pair. """
    matched_spotify_ids = set()
    matched_tidal_ids = set()

    # honor any pre-existing cache entries so they take priority and their Tidal id isn't reused
    for spotify_item in spotify_items:
        existing = cache.get(spotify_item['id'])
        if existing is not None:
            matched_spotify_ids.add(spotify_item['id'])
            matched_tidal_ids.add(existing)

    def _try_match(spotify_item, tidal_item) -> bool:
        if spotify_item['id'] in matched_spotify_ids or tidal_item.id in matched_tidal_ids:
            return False
        if match_fn(tidal_item, spotify_item, config):
            cache.insert((spotify_item['id'], tidal_item.id))
            matched_spotify_ids.add(spotify_item['id'])
            matched_tidal_ids.add(tidal_item.id)
            if on_match:
                on_match(spotify_item, tidal_item)
            return True
        return False

    # First pass: match each Tidal item to a Spotify item
    for tidal_item in tidal_items:
        if tidal_item.id in matched_tidal_ids:
            continue
        for spotify_item in spotify_items:
            if _try_match(spotify_item, tidal_item):
                break

    # Second pass: retry remaining Spotify items against remaining Tidal items
    for spotify_item in spotify_items:
        if spotify_item['id'] in matched_spotify_ids:
            continue
        for tidal_item in tidal_items:
            if _try_match(spotify_item, tidal_item):
                break

def populate_album_match_cache(spotify_albums: Sequence[dict], tidal_albums: Sequence[tidalapi.Album], config: Optional[dict] = None):
    """ Populate the album match cache with existing albums. """
    _populate_match_cache(spotify_albums, tidal_albums, album_match_cache, album_match, config,
                          on_match=lambda spotify_album, tidal_album: record_artist_matches_from_release(spotify_album, tidal_album, config))

def populate_artist_match_cache(spotify_artists: Sequence[dict], tidal_artists: Sequence[tidalapi.Artist], config: Optional[dict] = None):
    """ Populate the artist match cache with existing artists. """
    _populate_match_cache(spotify_artists, tidal_artists, artist_match_cache, artist_match, config)

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

    albums_to_search = get_new_spotify_albums(spotify_albums)
    if not albums_to_search:
        return

    # Search for each album on Tidal concurrently
    task_description = f"Searching Tidal for {len(albums_to_search)}/{len(spotify_albums)} albums"
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore, config))
    # return_exceptions so one album's non-retryable error doesn't abort the whole batch's search
    search_results = await atqdm.gather(*[repeat_on_request_error(tidal_album_search, a, semaphore, tidal_session) for a in albums_to_search], desc=task_description, return_exceptions=True)
    rate_limiter_task.cancel()

    # Add search results to cache
    for idx, spotify_album in enumerate(albums_to_search):
        result = search_results[idx]
        if isinstance(result, Exception):
            print(f"Error searching for album {spotify_album['id']}: {result}")
            result = None
        if result:
            album_match_cache.insert((spotify_album['id'], result.id))
            record_artist_matches_from_release(spotify_album, result, config)
        else:
            album_info = f"{spotify_album['id']}: {','.join([a['name'] for a in spotify_album['artists']])} - {spotify_album['name']}"
            add_not_found_item('album', album_info)
            color = ('\033[91m', '\033[0m')
            print(color[0] + "Could not find album " + album_info + color[1])

async def prepare_artist_sync(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ First phase of followed-artist sync: load the Spotify follows, resolve the ones already
        followed on Tidal, and register the remaining 'wanted' artists so that any subsequent
        track/album syncs harvest their Tidal ids from real matched releases. Must run before the
        track/album syncs. Returns (spotify_artists, old_tidal_artists) for the finish phase. """
    print("Loading followed artists from Spotify")
    spotify_artists = await get_followed_artists_from_spotify(spotify_session)
    print("Loading existing followed artists from Tidal")
    old_tidal_artists = await repeat_on_request_error(get_all_saved_artists, tidal_session.user)
    populate_artist_match_cache(spotify_artists, old_tidal_artists, config)
    wanted = {a['id'] for a in spotify_artists if a.get('id') and not artist_match_cache.get(a['id'])}
    set_wanted_artist_ids(wanted)
    print(f"{len(spotify_artists) - len(wanted)}/{len(spotify_artists)} followed artists already on Tidal; "
          f"{len(wanted)} to resolve from synced releases / top tracks")
    return spotify_artists, old_tidal_artists

async def resolve_residual_artists_on_tidal(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, spotify_artists: Sequence[dict], config: dict):
    """ Ground each still-unresolved wanted artist by matching one of their Spotify top tracks on
        Tidal (via the existing tidal_search) and reading the artist off that matched track — never a
        bare artist-name match. Artists whose top tracks can't be matched on Tidal are logged, not
        followed (a wrong same-name follow is worse than a miss). """
    residual = [a for a in spotify_artists
                if a.get('id') in _wanted_artist_ids and not artist_match_cache.get(a['id'])]
    if not residual:
        return

    max_tracks = config.get('artist_grounding_tracks', 3)
    market = config.get('country', 'from_token')

    async def _resolve(spotify_artist: dict, semaphore):
        # isolate per-artist failures so one artist's error doesn't abort the whole gather
        try:
            _get_top_tracks = lambda: spotify_session.artist_top_tracks(spotify_artist['id'], country=market)
            top = await repeat_on_request_error(asyncio.to_thread, _get_top_tracks)
            for track in ((top or {}).get('tracks') or [])[:max_tracks]:
                matched = await repeat_on_request_error(tidal_search, track, semaphore, tidal_session)
                if matched:
                    record_artist_matches_from_release(track, matched, config)
                    if artist_match_cache.get(spotify_artist['id']):
                        return
        except (requests.exceptions.RequestException, spotipy.exceptions.SpotifyException) as e:
            print(f"Error grounding artist {spotify_artist['name']}: {e}")
        # no top track could be grounded on Tidal -> do not follow an unverified same-name guess
        add_not_found_item('artist', spotify_artist['name'])

    task_description = f"Grounding {len(residual)}/{len(spotify_artists)} remaining artists on Tidal"
    semaphore = asyncio.Semaphore(config.get('max_concurrency', 10))
    rate_limiter_task = asyncio.create_task(_run_rate_limiter(semaphore, config))
    await atqdm.gather(*[_resolve(a, semaphore) for a in residual], desc=task_description)
    rate_limiter_task.cancel()

async def finish_artist_sync(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict, spotify_artists: Sequence[dict], old_tidal_artists: Sequence[tidalapi.Artist]):
    """ Second phase: after the library harvest, ground whatever's still unresolved via top tracks,
        then follow everything newly resolved that isn't already followed on Tidal. Runs after the
        track/album syncs. """
    await resolve_residual_artists_on_tidal(spotify_session, tidal_session, spotify_artists, config)
    existing_artist_ids = set(artist.id for artist in old_tidal_artists)
    new_tidal_artist_ids = []
    for spotify_artist in spotify_artists:
        match_id = artist_match_cache.get(spotify_artist['id'])
        if match_id and match_id not in existing_artist_ids:
            new_tidal_artist_ids.append(match_id)
    if new_tidal_artist_ids:
        await _add_items_to_tidal(new_tidal_artist_ids, "Following new artists on Tidal",
                                  lambda tid: add_artist_to_tidal_collection(tidal_session, tid), 'artist')
    else:
        print("No new artists to follow on Tidal")

async def sync_artists(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    """ Sync followed artists from Spotify to Tidal (standalone path: prepare + finish back-to-back).
        When run as part of a full sync, __main__ calls prepare_artist_sync before the track/album
        syncs and finish_artist_sync after, so artists are resolved from harvested releases first. """
    spotify_artists, old_tidal_artists = await prepare_artist_sync(spotify_session, tidal_session, config)
    await finish_artist_sync(spotify_session, tidal_session, config, spotify_artists, old_tidal_artists)

def sync_albums_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    asyncio.run(sync_albums(spotify_session, tidal_session, config))

def sync_artists_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    asyncio.run(sync_artists(spotify_session, tidal_session, config))

def prepare_artist_sync_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict):
    return asyncio.run(prepare_artist_sync(spotify_session, tidal_session, config))

def finish_artist_sync_wrapper(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session, config: dict, spotify_artists, old_tidal_artists):
    asyncio.run(finish_artist_sync(spotify_session, tidal_session, config, spotify_artists, old_tidal_artists))

def get_tidal_playlists_wrapper(tidal_session: tidalapi.Session) -> Mapping[str, tidalapi.Playlist]:
    tidal_playlists = asyncio.run(repeat_on_request_error(get_all_playlists, tidal_session.user))
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

