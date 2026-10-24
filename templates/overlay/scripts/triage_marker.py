#!/usr/bin/env python3
"""The one reference pattern for a triage marker (pr-review-and-merge.md rule 1.8).

A triage reply ends with a hidden marker naming the head sha it attests to and the finding ids it
answers: `<!-- triage:<sha> H1 H3 -->`. The ids are optional and space-separated; a marker with no
ids clears nothing. The merge lane and any CI re-review planner import this module instead of
writing their own pattern, so a reply in the core grammar is read the same way by both.

    from triage_marker import parse, cleared
    parse(body)            -> [(sha, ['H1', 'H3']), ...] in the order they appear
    cleared(body, head)    -> {'H1', 'H3'}: ids cleared for this head only

Run `python3 triage_marker.py --self-test` to check the forms. Python 3.9, stdlib only.
"""

from __future__ import annotations

import re
import sys

MARKER = re.compile(r"<!--\s*triage:([0-9a-f]{7,40})((?:\s+[A-Za-z]+[0-9]+)*)\s*-->")


def parse(body: str) -> list:
    """Every marker in the text as (sha, ids)."""
    return [(m.group(1), m.group(2).split()) for m in MARKER.finditer(body or "")]


def cleared(body: str, head: str) -> set:
    """Finding ids cleared for this head: only markers whose sha is a prefix of the head count."""
    out = set()
    for sha, ids in parse(body):
        if head and head.startswith(sha):
            out.update(ids)
    return out


def self_test() -> int:
    head = "abc1234def5678abc1234def5678abc1234def56"
    cases = [
        ("<!-- triage:abc1234 H1 H3 -->", {"H1", "H3"}),
        ("<!--triage:abc1234def5678abc1234def5678abc1234def56 H2-->", {"H2"}),
        ("<!-- triage:abc1234 -->", set()),
        ("<!-- triage:fff0000 H1 -->", set()),
        ("text <!-- triage:abc1234 H1 --> more <!-- triage:abc1234 B2 -->", {"H1", "B2"}),
        ("<!-- triage: H1 -->", set()),
    ]
    bad = [
        f"{body!r}: got {sorted(cleared(body, head))}, want {sorted(want)}"
        for body, want in cases
        if cleared(body, head) != want
    ]
    for b in bad:
        print(b)
    print("triage_marker: ok" if not bad else f"triage_marker: {len(bad)} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else 0)
