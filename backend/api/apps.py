import os
import sys
import threading

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self) -> None:
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return

        def _start() -> None:
            from .oro import start_overview_poller
            from .store import initialize_database

            initialize_database()
            start_overview_poller()

        threading.Thread(target=_start, daemon=True, name="oro-db-init").start()
