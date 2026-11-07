"""
optional.py
Purpose: Registers the optional modules (log intake, reports) with the route registry, and only the ones a consumer turned on. With
         neither setting present nothing is imported, no route or background task is added and no file is created.
Date:    2026-11-07

Settings: OPSCENTER_LOG_INTAKE   any non empty value other than 0, false or off turns the log intake routes on
          OPSCENTER_REPORTS      the same for the reports routes
Providers: OPSCENTER_LOG_INTAKE_PROVIDER and OPSCENTER_REPORTS_PROVIDER (`path/to/file.py:ClassName`), see each module's http_routes.py.
API:      enabled(name) -> bool     register(registry) -> [names of the modules registered]
"""

import os
import sys
from pathlib import Path

MODULES = Path(__file__).resolve().parent / "modules"
OFF = ("", "0", "false", "off", "no")


def enabled(name):
    return os.environ.get(name, "").strip().lower() not in OFF


def register(r):
    on = []
    if enabled("OPSCENTER_LOG_INTAKE") or enabled("OPSCENTER_REPORTS"):
        if str(MODULES) not in sys.path:
            sys.path.insert(0, str(MODULES))
        import optional_provider as op
    if enabled("OPSCENTER_LOG_INTAKE"):
        from log_intake import http_routes

        http_routes.register(r, op.load("OPSCENTER_LOG_INTAKE_PROVIDER"))
        on.append("log_intake")
    if enabled("OPSCENTER_REPORTS"):
        from reports import http_routes

        http_routes.register(r, op.load("OPSCENTER_REPORTS_PROVIDER"))
        on.append("reports")
    return on
