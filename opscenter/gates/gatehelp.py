"""Test helper: run a gate entry point and return what it printed and how it exited."""

import contextlib
import io


def run_gate(fn, *args):
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            fn(*args)
        except SystemExit as e:
            code = e.code
    return buf.getvalue(), code


def is_silent(out):
    return out.strip().splitlines()[-1:] == ['{"wakeAgent": false}']
