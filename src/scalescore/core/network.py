from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}


def validate_remote_url(
    url: str,
    *,
    setting_name: str,
    require_https: bool,
    allow_private_network: bool,
) -> None:
    """Validate outbound integration URLs used by remote connectors."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{setting_name} must use http or https")
    if require_https and parsed.scheme != "https":
        raise ValueError(f"{setting_name} must use https outside development/testing")

    host = parsed.hostname
    if not host:
        raise ValueError(f"{setting_name} must include a hostname")

    if allow_private_network:
        return

    normalized_host = host.strip().lower()
    if normalized_host in LOCALHOST_NAMES:
        raise ValueError(f"{setting_name} cannot target localhost by default")

    try:
        host_ip = ip_address(normalized_host)
    except ValueError:
        return

    if (
        host_ip.is_loopback
        or host_ip.is_private
        or host_ip.is_link_local
        or host_ip.is_reserved
        or host_ip.is_multicast
    ):
        raise ValueError(f"{setting_name} cannot target private or local IP ranges")
