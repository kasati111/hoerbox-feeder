"""Recognize the hörbert device by its User-Agent for log lines.

Observed live traffic: the device sends "hoerbert/<version>" (see
DEVELOPER.md). Logging that raw string works but is one more thing to
recognize by eye in grep output next to browsers/curl/podcast clients --
this normalizes it to a fixed "Hörbert" label instead.
"""
from fastapi import Request

_HOERBERT_UA_MARKER = "hoerbert"


def client_info(request: Request) -> str:
    client = request.client.host if request.client else "?"
    raw_ua = request.headers.get("user-agent") or "-"
    ua = "Hörbert" if _HOERBERT_UA_MARKER in raw_ua.lower() else raw_ua
    return f"client={client} ua={ua}"
