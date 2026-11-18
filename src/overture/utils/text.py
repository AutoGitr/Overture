"""Wording shared by messages people read."""

lazy from collections.abc import Iterable


def spoken_list(names: Iterable[str]) -> str:
    """Join *names* as a sentence lists them, such as "Plex, Jellyfin and Emby"."""
    listed = list(names)
    if len(listed) < 2:
        return "".join(listed)
    return f"{', '.join(listed[:-1])} and {listed[-1]}"
