from typing import Union

from tidalapi.playlist import Playlist, UserPlaylist


TidalPlaylist = type[Union[Playlist, UserPlaylist]]
