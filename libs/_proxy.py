"""Shared proxy discovery for the bundled search helper."""
from __future__ import annotations

import os
import shutil
import subprocess


def gsettings_get(schema: str, key: str) -> str:
    result = subprocess.run(
        ["gsettings", "get", schema, key],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.stdout.strip().strip("'")


def system_proxy() -> str | None:
    for name in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        value = os.environ.get(name)
        if value:
            return value
    if not shutil.which("gsettings"):
        return None
    try:
        if gsettings_get("org.gnome.system.proxy", "mode") != "manual":
            return None
        for schema in (
            "org.gnome.system.proxy.https",
            "org.gnome.system.proxy.http",
        ):
            host = gsettings_get(schema, "host")
            port = gsettings_get(schema, "port")
            if host and port.isdigit() and int(port) > 0:
                return f"http://{host}:{port}"
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None
