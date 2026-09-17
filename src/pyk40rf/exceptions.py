"""Error taxonomy for :mod:`pyk40rf`."""

from __future__ import annotations

__all__ = [
    "K40AuthError",
    "K40ConnectionError",
    "K40Error",
    "K40ForbiddenError",
    "K40NotFoundError",
    "K40ProximityError",
    "K40ResponseError",
]


class K40Error(Exception):
    """Base class for every error raised by this library."""


class K40ConnectionError(K40Error):
    """The gateway could not be reached, or the transport failed."""


class K40AuthError(K40Error):
    """Credentials or bearer token were rejected (HTTP 401/403)."""


class K40ProximityError(K40AuthError):
    """Token request refused because physical proximity was not proven.

    The gateway answers HTTP 412 ``physical_proximity_unproven`` unless both
    conditions hold: the WLAN + radio buttons were pressed within the last few
    minutes, and the request originates from the gateway's own subnet.
    """


class K40ForbiddenError(K40Error):
    """The gateway refused this resource (HTTP 403).

    Deliberately *not* an :class:`K40AuthError`. The gateway answers 403 for
    paths it will not serve to anyone -- a resource outside the published
    specification, for instance -- while a token it no longer accepts gets a
    401. Treating the two alike lets one refused resource among hundreds look
    like a revoked token and take the whole connection down.
    """


class K40NotFoundError(K40Error):
    """The resource does not exist on this installation (HTTP 404).

    Expected during discovery: the API spec declares ids for every possible
    installation (``hs1``-``hs6``, ``hc1``-``hc4``, ...), and a given device
    only implements a subset.
    """


class K40ResponseError(K40Error):
    """The gateway answered with something this client cannot interpret."""
