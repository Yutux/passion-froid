from django.apps import AppConfig


class PortalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'portal'

    def ready(self):
        import os
        import sys

        from django.conf import settings

        if "runserver" in sys.argv and (os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv):
            from .ai_worker import start_worker
            start_worker()

        if not getattr(settings, "PASSIONFROID_AUTO_SYNC_ON_STARTUP", False):
            return
        if "runserver" not in sys.argv:
            return
        if os.environ.get("RUN_MAIN") != "true":
            return

        from .auto_sync import start_background_sync

        start_background_sync(reason="startup")
