import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CLEANUP_INTERVAL_SECONDS = 600  # 10 minutes


class SessionService:
    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._start_cleanup_thread()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self._lock:
            self._sessions[session_id] = {
                "created_at": time.time(),
                "last_accessed": time.time(),
                "data": {},
            }
        logger.debug("Session created: %s", session_id)
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if time.time() - session["created_at"] > settings.SESSION_TTL_SECONDS:
                del self._sessions[session_id]
                logger.debug("Session expired and removed: %s", session_id)
                return None
            session["last_accessed"] = time.time()
            return session["data"]

    def update_session(self, session_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["data"].update(data)
                self._sessions[session_id]["last_accessed"] = time.time()
            else:
                logger.warning("Attempted update on non-existent session: %s", session_id)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def count_sessions(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    def _cleanup_expired(self) -> None:
        while True:
            time.sleep(CLEANUP_INTERVAL_SECONDS)
            now = time.time()
            with self._lock:
                expired = [
                    sid
                    for sid, session in self._sessions.items()
                    if now - session["created_at"] > settings.SESSION_TTL_SECONDS
                ]
                for sid in expired:
                    del self._sessions[sid]
            if expired:
                logger.info("Cleaned up %d expired sessions.", len(expired))

    def _start_cleanup_thread(self) -> None:
        thread = threading.Thread(target=self._cleanup_expired, daemon=True)
        thread.start()


session_service = SessionService()
