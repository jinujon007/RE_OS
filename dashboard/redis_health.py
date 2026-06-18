"""T-1262: Background Redis health-check loop.

Starts a daemon thread that pings Redis every 15 seconds.
Resets _REDIS_CLIENT_INSTANCE to False on ping failure.
Attempts lazy reconnect via _attempt_redis_connect when client is False.
Updates `redis_connected` Prometheus gauge (R1.16) so Grafana
can alert on Redis state without polling the app.
"""

import logging
import threading
import time

from dashboard import state as _state

_logger = logging.getLogger("re_os.dashboard")

_HEALTH_CHECK_INTERVAL = 15

try:
    from config.metrics import redis_connected as _redis_gauge
except Exception:
    _redis_gauge = None  # Prometheus not available — health check still works


def _redis_health_loop(stop_event: threading.Event | None = None):
    """Background loop: ping Redis every 15s, reset client on failure.

    Top-level exception guard prevents the loop from dying silently
    on transient errors (R1.2).

    Args:
        stop_event: Optional threading.Event to signal shutdown.
                    If None, runs forever (daemon thread).
    """
    if stop_event is None:
        stop_event = threading.Event()
    while not stop_event.is_set():
        try:
            _run_health_check()
        except Exception:
            _logger.exception("[Redis health] unexpected error in health check — continuing")
        stop_event.wait(_HEALTH_CHECK_INTERVAL)


def _set_redis_gauge(connected: bool):
    """Update the redis_connected Prometheus gauge (R1.16). Module-level import avoids
    repeated lazy lookups on every 15s health check (R3.1)."""
    if _redis_gauge is not None:
        try:
            _redis_gauge.set(1 if connected else 0)
        except Exception:
            pass


def _run_health_check():
    """Single health-check iteration — resets client on ping failure.

    Atomicity: reads _REDIS_CLIENT_INSTANCE once via _get_redis_client()
    to avoid the was_down race (R1.3). Uses _state._attempt_redis_connect
    directly instead of re-importing (R1.4).
    Updates redis_connected Prometheus gauge on every iteration (R1.16).
    """
    was_down = _state._REDIS_CLIENT_INSTANCE is False
    client = _state._get_redis_client()
    if client is not None:
        try:
            client.ping()
        except Exception:
            _logger.debug("[Redis health] ping failed — resetting client")
            _state._REDIS_CLIENT_INSTANCE = False
            _set_redis_gauge(False)
        else:
            _set_redis_gauge(True)
            if was_down:
                _logger.info("Redis reconnected")
    elif _state._REDIS_CLIENT_INSTANCE is False:
        _state._attempt_redis_connect()
        if _state._REDIS_CLIENT_INSTANCE is not False:
            _logger.info("Redis reconnected")
            _set_redis_gauge(True)
        else:
            _set_redis_gauge(False)
