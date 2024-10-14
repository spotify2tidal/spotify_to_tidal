# tests/unit/test_auth.py

import pytest
import spotipy
import tidalapi
import yaml
import sys
from unittest import mock
from spotify_to_tidal.auth import open_spotify_session, open_tidal_session, SPOTIFY_SCOPES


def test_open_spotify_session(mocker):
    # Mock the SpotifyOAuth class
    mock_spotify_oauth = mocker.patch(
        "spotify_to_tidal.auth.spotipy.SpotifyOAuth", autospec=True
    )
    mock_spotify_instance = mocker.patch(
        "spotify_to_tidal.auth.spotipy.Spotify", autospec=True
    )

    # Define a mock configuration
    mock_config = {
        "username": "test_user",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "redirect_uri": "http://localhost/",
        "open_browser": True,
    }

    # Create a mock SpotifyOAuth instance
    mock_oauth_instance = mock_spotify_oauth.return_value
    mock_oauth_instance.get_access_token.return_value = "mock_access_token"

    # Call the function under test
    spotify_instance = open_spotify_session(mock_config)

    # Assert that the SpotifyOAuth was called with correct parameters
    mock_spotify_oauth.assert_called_once_with(
        username="test_user",
        scope=SPOTIFY_SCOPES,
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="http://localhost/",
        requests_timeout=2,
        open_browser=True,
    )

    # Assert that the Spotify instance was created
    mock_spotify_instance.assert_called_once_with(oauth_manager=mock_oauth_instance)
    assert spotify_instance == mock_spotify_instance.return_value


def test_open_spotify_session_oauth_error(mocker):
    # Mock the SpotifyOAuth class and simulate an OAuth error
    mock_spotify_oauth = mocker.patch(
        "spotify_to_tidal.auth.spotipy.SpotifyOAuth", autospec=True
    )
    mock_spotify_oauth.return_value.get_access_token.side_effect = (
        spotipy.SpotifyOauthError("mock error")
    )

    # Define a mock configuration
    mock_config = {
        "username": "test_user",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "redirect_uri": "http://localhost/",
    }

    # Mock sys.exit to prevent the test from exiting
    mock_sys_exit = mocker.patch("sys.exit")

    # Call the function under test and assert sys.exit is called
    open_spotify_session(mock_config)
    mock_sys_exit.assert_called_once()
