> NOTE: this project is forked from: https://github.com/spotify2tidal/spotify_to_tidal and includes the following **enhanced features**:
>
> - **NEW**: Support for synchronizing followed artists
> - **NEW**: Advanced fuzzy matching with configurable thresholds  
> - **NEW**: Consolidated logging of all unmatched items
> - **ENHANCED**: Support for synchronizing saved albums (improved matching algorithms)
>
> See https://github.com/spotify2tidal/spotify_to_tidal/issues/151 and https://github.com/spotify2tidal/spotify_to_tidal/pull/150

A command line tool for importing your Spotify playlists into Tidal. Due to various performance optimisations, it is particularly suited for periodic synchronisation of very large collections.

Installation
-----------
Clone this git repository and then run:

```bash
# Create and activate virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the project
pip install -e .
```

**Note**: Always activate the virtual environment before running any commands:
```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

Setup
-----
0. Rename the file example_config.yml to config.yml
0. Go [here](https://developer.spotify.com/documentation/general/guides/authorization/app-settings/) and register a new app on developer.spotify.com.
0. Copy and paste your client ID and client secret to the Spotify part of the config file
0. Copy and paste the value in 'redirect_uri' of the config file to Redirect URIs at developer.spotify.com and press ADD
0. Enter your Spotify username to the config file

Usage
----
To synchronize all of your Spotify playlists, favourites, albums and followed artists with your Tidal account run the following from the project root directory:
Windows ignores python module paths by default, but you can run them using `python3 -m spotify_to_tidal`

```bash
spotify_to_tidal
```

Use `--sync-playlists`, `--sync-favorites`, `--sync-albums` and/or `--sync-artists` to limit the sync to one or more types. For example:

Synchronise your 'Liked Songs':

```bash
spotify_to_tidal --sync-favorites
```

Synchronize your saved albums:

```bash
spotify_to_tidal --sync-albums
```

**NEW**: Synchronize your followed artists:

```bash
spotify_to_tidal --sync-artists
```

Options can be combined, for example:

```bash
spotify_to_tidal --sync-favorites --sync-albums --sync-artists
```

You can also just synchronize a specific playlist by doing the following:

```bash
spotify_to_tidal --uri 1ABCDEqsABCD6EaABCDa0a # accepts playlist id or full playlist uri
```

See example_config.yml for more configuration options, and `spotify_to_tidal --help` for more options.

**NEW**: After each sync, a consolidated log file `items not found.txt` is created containing all tracks, albums, and artists that couldn't be matched on Tidal, organized by type for easy review.

---

#### Join our amazing community as a code contributor
<br><br>
<a href="https://github.com/spotify2tidal/spotify_to_tidal/graphs/contributors">
  <img class="dark-light" src="https://contrib.rocks/image?repo=spotify2tidal/spotify_to_tidal&anon=0&columns=25&max=100&r=true" />
</a>
