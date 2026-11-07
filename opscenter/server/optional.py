"""
optional.py
Purpose: Registers the optional modules (log intake, reports) with the route registry, and only the ones a consumer turned on. With
         neither setting present nothing is imported, no route or background task is added and no file is created.
Date:    2026-11-07

Settings: OPSCENTER_LOG_INTAKE   any non empty value other than 0, false or off turns the log intake routes on
          OPSCENTER_DOCS_DRIFT_PROVIDER   a provider (path/to/file.py:ClassName) is the opt in for the docs drift feed (docs_drift.py)
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
    if (
        enabled("OPSCENTER_LOG_INTAKE")
        or enabled("OPSCENTER_REPORTS")
        or os.environ.get("OPSCENTER_DOCS_DRIFT_PROVIDER", "").strip()
    ):
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
    if os.environ.get("OPSCENTER_DOCS_DRIFT_PROVIDER", "").strip():
        # The provider is the opt in: with none there is no route and no tab (a null slot hides the page).
        import docs_drift

        docs_drift.register(r, op.load("OPSCENTER_DOCS_DRIFT_PROVIDER"))
        on.append("docs_drift")
    return on
