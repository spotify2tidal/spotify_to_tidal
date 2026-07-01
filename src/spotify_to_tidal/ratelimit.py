""" Request-resilience helpers shared by the Spotify and Tidal sync paths: a retry wrapper that
    backs off on transient errors (honoring Retry-After) and a leaky-bucket rate limiter. """

import asyncio
import datetime
from email.utils import parsedate_to_datetime
import sys
import traceback

import requests
import spotipy
import tidalapi


async def repeat_on_request_error(function, *args, remaining=5, **kwargs):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    try:
        return await function(*args, **kwargs)
    except (tidalapi.exceptions.TooManyRequests, requests.exceptions.RequestException, spotipy.exceptions.SpotifyException) as e:
        # Locate the underlying HTTP response, which may be on the exception directly
        # (requests) or on the wrapped cause (tidalapi TooManyRequests)
        response = getattr(e, 'response', None)
        if response is None and getattr(e, '__cause__', None) is not None:
            response = getattr(e.__cause__, 'response', None)

        # Only retry transient failures: rate limits (429), server errors (5xx), and
        # connection/timeout errors (no HTTP status). Other 4xx (e.g. 412 precondition,
        # 400/403/404) won't recover by retrying, so fail fast instead of burning the backoff.
        status = getattr(response, 'status_code', None)
        if status is None:
            status = getattr(e, 'http_status', None)  # spotipy.SpotifyException
        is_rate_limit = isinstance(e, tidalapi.exceptions.TooManyRequests) or status == 429
        retryable = is_rate_limit or status is None or status >= 500
        if not retryable:
            print(f"{str(e)} is not retryable (HTTP {status}); aborting without retry")
            if response is not None:
                print(f"Response message: {response.text}")
            raise

        if remaining:
            print(f"{str(e)} occurred, retrying {remaining} times")
        else:
            print(f"{str(e)} could not be recovered")

        if response is not None:
            print(f"Response message: {response.text}")
            print(f"Response headers: {response.headers}")

        if not remaining:
            print("Aborting sync")
            print(f"The following arguments were provided:\n\n {str(args)}")
            print(traceback.format_exc())
            sys.exit(1)

        # Honor the server's Retry-After header when present, otherwise fall back to the backoff schedule
        retry_after = None
        if response is not None:
            retry_after_header = response.headers.get('Retry-After') or response.headers.get('retry-after')
            if retry_after_header:
                try:
                    retry_after = int(retry_after_header)
                except ValueError:
                    # Retry-After may also be an HTTP-date (RFC 7231); convert it to a delay in seconds
                    try:
                        retry_dt = parsedate_to_datetime(retry_after_header)
                        delay = (retry_dt - datetime.datetime.now(retry_dt.tzinfo)).total_seconds()
                        retry_after = max(0, int(delay))
                    except (TypeError, ValueError):
                        retry_after = None
        if retry_after is not None:
            print(f"Waiting {retry_after} seconds (Retry-After header) before retrying")
            await asyncio.sleep(retry_after)
        else:
            sleep_schedule = {5: 1, 4:10, 3:60, 2:5*60, 1:10*60} # sleep variable length of time depending on retry number
            await asyncio.sleep(sleep_schedule.get(remaining, 1))
        return await repeat_on_request_error(function, *args, remaining=remaining-1, **kwargs)


async def _run_rate_limiter(semaphore: asyncio.Semaphore, config: dict):
    ''' Leaky bucket algorithm for rate limiting. Periodically releases items from semaphore at rate_limit'''
    # treat an absent/zero/negative rate_limit as the default to avoid division by zero
    rate_limit = config.get('rate_limit', 10) or 10
    _sleep_time = config.get('max_concurrency', 10)/rate_limit/4 # aim to sleep approx time to drain 1/4 of 'bucket'
    t0 = datetime.datetime.now()
    while True:
        await asyncio.sleep(_sleep_time)
        t = datetime.datetime.now()
        dt = (t - t0).total_seconds()
        new_items = round(rate_limit*dt)
        t0 = t
        [semaphore.release() for _ in range(new_items)] # leak new_items from the 'bucket'
