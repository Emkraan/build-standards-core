#!/usr/bin/env python3
"""
Purpose: Map repo relative paths to the live paths the running install reads them from (the inverse of an export script that
         copies live files into the repo). The map is data: a JSON list of [repo prefix, live prefix] pairs in LIVEPATH_MAP
         (a file path) or inline; no map means every path is unmapped.
Usage: livepath.py <repo-path>...   (prints one live path per line; unmapped paths are skipped)
Config: LIVEPATH_MAP  a JSON file holding [["scripts/", "~/live/scripts/"], ...]; a leading ~ is expanded
"""

import json
import os
import sys


def _load():
    f = os.environ.get("LIVEPATH_MAP")
    data = []
    if f:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = []
    return (
        [(str(a), os.path.expanduser(str(b))) for a, b in data if isinstance(data, list)]
        if isinstance(data, list)
        else []
    )


MAP = _load()


def live_path(rel):
    for prefix, target in MAP:
        if rel.startswith(prefix):
            return target + rel[len(prefix) :]
    return None


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = live_path(arg)
        if p:
            print(p)
