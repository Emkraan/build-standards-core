"""
optional.py
Purpose: Registers the optional modules (log intake, reports) with the route registry, and only the ones a consumer turned on. With
         neither setting present nothing is imported, no route or background task is added and no file is created.
Date:    2026-11-07

Settings: OPSCENTER_LOG_INTAKE   any non empty value other than 0, false or off turns the log intake routes on
          OPSCENTER_DOCS_DRIFT_PROVIDER   a provider (path/to/file.py:ClassName) is the opt in for the docs drift feed (docs_drift.py)
          OPSCENTER_BUILDS_PROVIDER       the same for the active builds feed (active_builds.py), read only
          OPSCENTER_EXTENSIONS_PROVIDER   the same for the extension manifest (extensions.py): pages a consumer adds to the rail, read only
          OPSCENTER_EXTENSIONS_FILE       the data-only form: a JSON file of pages and rows instead of a provider class
          OPSCENTER_DOCS_PIPELINE_PROVIDER the same for the document pipeline (doc_pipeline.py): queue, draft, preview, suggest, decide, restore, guarded publish
          OPSCENTER_PHONE_PROVIDER        the same for phone pairing and alerts (phone_pairing.py): pair, devices, test, remove
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
        or os.environ.get("OPSCENTER_BUILDS_PROVIDER", "").strip()
        or os.environ.get("OPSCENTER_EXTENSIONS_PROVIDER", "").strip()
        or os.environ.get("OPSCENTER_PHONE_PROVIDER", "").strip()
        or os.environ.get("OPSCENTER_EXTENSIONS_FILE", "").strip()
        or os.environ.get("OPSCENTER_DOCS_PIPELINE_PROVIDER", "").strip()
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
    if os.environ.get("OPSCENTER_BUILDS_PROVIDER", "").strip():
        # The provider is the opt in and the route is read only: with none there is no route and the panel is hidden.
        import active_builds

        active_builds.register(r, op.load("OPSCENTER_BUILDS_PROVIDER"))
        on.append("active_builds")
    if os.environ.get("OPSCENTER_EXTENSIONS_PROVIDER", "").strip():
        # The provider is the opt in and both routes are read only: with none there is no route and the rail shows nothing extra.
        import extensions

        extensions.register(r, op.load("OPSCENTER_EXTENSIONS_PROVIDER"))
        on.append("extensions")
    if (
        os.environ.get("OPSCENTER_EXTENSIONS_FILE", "").strip()
        and not os.environ.get("OPSCENTER_EXTENSIONS_PROVIDER", "").strip()
    ):
        # The data-only form of the same slot: a JSON file, no code (extensions.FileProvider).
        import extensions

        extensions.register(
            r, extensions.FileProvider(os.environ["OPSCENTER_EXTENSIONS_FILE"].strip())
        )
        on.append("extensions")
    if os.environ.get("OPSCENTER_DOCS_PIPELINE_PROVIDER", "").strip():
        # The provider is the opt in: with none there is no route and the Knowledge tab is hidden (DESIGN.md 12.97).
        import doc_pipeline

        doc_pipeline.register(r, op.load("OPSCENTER_DOCS_PIPELINE_PROVIDER"))
        on.append("doc_pipeline")
    if os.environ.get("OPSCENTER_PHONE_PROVIDER", "").strip():
        # The provider is the opt in: with none there is no route and the page shows the setup steps. Pair is loopback only (12.77).
        import phone_pairing

        phone_pairing.register(r, op.load("OPSCENTER_PHONE_PROVIDER"))
        on.append("phone_pairing")
    return on
