"""Shared rate limiter.

Limits are keyed on client IP. When running behind a reverse proxy, start
uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` so the real client
address is used instead of the proxy's.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
