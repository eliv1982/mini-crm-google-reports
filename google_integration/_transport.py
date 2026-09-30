from __future__ import annotations

import http.client
import socket

import httplib2
from google.auth.exceptions import TransportError

# Exceptions that escape googleapiclient's HttpRequest.execute() when the network
# fails (verified against the installed stack, no retries configured):
#   - httplib2.HttpLib2Error: the documented transport error; DNS failures arrive as
#     its subclass httplib2.ServerNotFoundError.
#   - http.client.HTTPException: httplib2 re-raises dropped or malformed connections.
#   - OSError: httplib2 and googleapiclient re-raise socket errors unchanged
#     (TimeoutError, ConnectionError, ssl.SSLError, and a plain OSError for
#     unreachable networks or hosts).
#   - google.auth.exceptions.TransportError: an expired token is refreshed inside
#     execute(), and that request fails through google-auth's own transport.
TRANSPORT_ERRORS: tuple[type[Exception], ...] = (
    httplib2.HttpLib2Error,
    http.client.HTTPException,
    OSError,
    TransportError,
)


def describe_transport_error(error: Exception) -> str:
    # str(error) embeds library internals and localized OS text; the original
    # exception stays available through exception chaining.
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "the request timed out"
    return "could not connect to Google"
