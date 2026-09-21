import json
import threading
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command


LOCK_FILE = Path(settings.BASE_DIR) / ".passionfroid_sync.lock"
STATUS_FILE = Path(settings.BASE_DIR) / "passionfroid_sync_status.json"


def get_sync_status() -> dict:
    if not STATUS_FILE.exists():
        return {"running": False, "message": "Aucune synchronisation lancee."}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"running": False, "message": "Statut illisible."}
    data["running"] = LOCK_FILE.exists()
    return data


def start_background_sync(reason: str = "manual", skip_ai: bool | None = None) -> bool:
    if LOCK_FILE.exists():
        return False

    thread = threading.Thread(
        target=_run_sync,
        kwargs={
            "reason": reason,
            "skip_ai": settings.PASSIONFROID_AUTO_SYNC_SKIP_AI if skip_ai is None else skip_ai,
        },
        daemon=True,
    )
    thread.start()
    return True


def _write_status(**kwargs):
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **kwargs,
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _run_sync(reason: str, skip_ai: bool):
    try:
        LOCK_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
        _write_status(
            running=True,
            success=None,
            reason=reason,
            message="Scraping PassionFroid puis import Cloudinary en cours.",
        )

        args = []
        if skip_ai:
            args.append("--skip-ai")
        call_command("sync_passionfroid_media", *args)

        _write_status(
            running=False,
            success=True,
            reason=reason,
            message="Synchronisation terminee.",
        )
    except Exception as exc:
        _write_status(
            running=False,
            success=False,
            reason=reason,
            message=str(exc),
        )
    finally:
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
