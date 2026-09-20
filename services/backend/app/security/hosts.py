from urllib.parse import urlsplit


def is_allowed_host(host_header: str, allowed_hosts: list[str]) -> bool:
    try:
        parts = urlsplit(f"//{host_header}")
        _ = parts.port
    except ValueError:
        return False
    return parts.hostname is not None and parts.hostname in allowed_hosts
