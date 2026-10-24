# Python Scripting Standard

Version: 1.0 | Last reviewed: 2026-10-13 | Status: current | Scope: Python (scheduled jobs, local tools, CI scripts)

How Python scripts are written when they run unattended on a schedule, behind a local tool or in
CI. This doc is the source of truth. Where a reference implementation differs, the implementation
is fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions").

Related: [Local Ops App Standard](local-ops-app.md) (stack, state files, the read-only module
conventions), [Secrets and Credentials](secrets-and-credentials.md),
[Automation Safety](automation-safety.md).

---

## 1. Rules

1. **Code runs on the interpreter floor.** The floor is the oldest interpreter that runs the code (parameter, default 3.9 where the OS python is the runtime). Every module with annotations starts with `from __future__ import annotations`, no newer syntax is used, and CI runs on the floor.
   - Prevents: a script that passes on a developer's newer python and crashes at import on the host, for example `X | None` evaluated at def time on 3.9.
   - Acceptance (overlay-ci): the `core-ci.yml` job `core-python` runs on the floor from the parameters sheet and runs the test command there.
2. **Standard library first.** Use a third-party package only when the standard library cannot do the job, pin it with hashes, and never install packages from inside a script at run time.
   - Prevents: a scheduled job that breaks when an unpinned dependency moves, and a supply chain step hidden inside a run.
   - Acceptance (review): every import outside the standard library is listed in a pinned requirements file with a reason.
3. **No secrets in argv, environment dumps or logs.** Pass secrets on stdin, in a mode 0600 file or by reading the secret store in process. Never log a command line, environment or response body that can carry one, and redact secret-shaped values in errors.
   - Prevents: a token visible to every local user through the process list, or kept forever in a log or a transcript.
   - Acceptance (review): no secret is passed as a subprocess argument and the log helpers redact.
4. **State files are written atomically.** Write to a temp file in the same directory, flush and fsync, then `os.replace` over the target. Sensitive files are created with mode 0600. Each file has exactly one named writer.
   - Prevents: a half-written JSON file after a crash or a full disk, which the next run reads as empty state.
   - Acceptance (test): tests write through the helper and assert the target is either old or new, never partial.
5. **Scheduled runs cannot overlap.** A job that a scheduler starts takes a non-blocking exclusive lock on a lock file and exits 0 with one skip line when another run holds it. The lock is released by process exit.
   - Prevents: two runs racing on the same state file or posting the same item twice when one run is slow.
   - Acceptance (test): a test holds the lock and asserts a second run exits with the skip line and writes nothing.
6. **Every external path is overridable for tests.** State directories, binaries (`gh`, cloud CLIs) and endpoints come from environment overrides with production defaults. Tests set them inline per command, never exported into a shared shell.
   - Prevents: a test that writes real state or calls a real API, and a fake binary that leaks into a later live run.
   - Acceptance (test): the suite runs with every override pointed at scratch paths and fake binaries.
7. **Tests use synthetic data and pin every fixed bug.** Tests run against fixtures and synthetic records, never real ones. Each fixed bug adds a regression case that fails on the old code.
   - Prevents: test runs that touch real items, and a fixed bug quietly coming back.
   - Acceptance (test): the stdlib `unittest` suite runs offline, and each fix PR names its regression case.
8. **Subprocesses go through one helper.** Call external commands with an argument list (no `shell=True`), a timeout, and one helper that turns a missing binary, a timeout or a non-zero exit into an error value. Tests patch that helper.
   - Prevents: a hung CLI that blocks a scheduler forever, and shell injection through a value.
   - Acceptance (lint): `script_lint` PY001 finds no `shell=True` or shell helper, and review finds no `subprocess` call outside the helper.
9. **Reads fail closed and exits are meaningful.** A failed or partial read is an error, never "nothing found". Exit 0 on success, 1 on failure, and other codes only when documented (for example 2 for sign-in needed).
   - Prevents: a broken source silently closing every open item, and a scheduler that cannot tell a skip from a failure.
   - Acceptance (test): tests feed a failing source and assert a non-zero exit and no destructive write.
10. **Lint and format with a committed ruff config.** `pyproject.toml` holds the ruff config with `target-version` equal to the floor, and CI runs `ruff check` and `ruff format --check`.
    - Prevents: newer-syntax upgrades that break the floor, and style churn in every diff.
    - Acceptance (overlay-ci): the `core-ci.yml` job `core-python` checks the committed ruff config targets the floor and runs both ruff commands.

## 2. The interpreter floor

- Set the floor per consumer in `standards-local/parameters.md`. Where scripts run under the OS
  python of a workstation, the floor is that version.
- `from __future__ import annotations` makes annotations strings, so `X | None` and `list[str]` in
  signatures are safe on 3.9. It does not make them safe at run time: `isinstance(x, int | str)`,
  `match` statements and parenthesised context managers still need 3.10.
- Run every changed script with the floor interpreter itself before pushing, not only the newest.

## 3. Atomic writes and locks

```python
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import tempfile


def write_json_atomic(path: pathlib.Path, data: object, mode: int = 0o600) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def single_run(lock_path: pathlib.Path):
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh  # keep a reference for the life of the run
```

- The temp file lives in the target's directory so `os.replace` is a rename on one filesystem.
- A read-modify-write on a file shared with another writer takes the same lock around the read and
  the write.
- Never delete a lock file because it looks old. A lock held by `flock` is released when the
  holder exits, so a stale file holds nothing.

## 4. Environment overrides

```python
STATE_DIR = pathlib.Path(
    os.environ.get("APP_STATE_DIR", str(pathlib.Path.home() / ".app" / "state"))
)
GH_BIN = os.environ.get("APP_GH_BIN", "gh")
```

- A process started by a service manager often has a minimal `PATH`. Resolve binaries to absolute
  paths at start-up and fail with one clear line when one is missing.
- Run tests as `APP_STATE_DIR=<scratch> APP_GH_BIN=<fake> python3 -m unittest ...`, and unset any
  override before a live check.

## 5. Ruff configuration

```toml
[tool.ruff]
target-version = "py39"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP"]

[tool.ruff.format]
quote-style = "single"
```

`target-version` keeps `UP` from rewriting code into syntax the floor cannot run.

## 6. Checklist

- [ ] Runs on the floor interpreter, `from __future__ import annotations` where annotated.
- [ ] Standard library only, or pinned dependencies with a reason.
- [ ] No secret in argv, logs or error text.
- [ ] Atomic writes with mode 0600 for sensitive files, one writer per file.
- [ ] Scheduled entry point takes a non-blocking lock.
- [ ] Paths, binaries and endpoints overridable, tests set them inline.
- [ ] Synthetic fixtures and a regression case per fixed bug.
- [ ] One subprocess helper with a timeout, no `shell=True`.
- [ ] Failed reads exit non-zero and never close or delete anything.
- [ ] `ruff check` and `ruff format --check` pass with the committed config.
