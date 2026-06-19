from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()
_LLM = _SETTINGS.llm

_thread_local = threading.local()


class LLMModuleError(RuntimeError):
    pass


def _get_db_connection(db_path):
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        _thread_local.conn = conn
    return _thread_local.conn


def _close_db_connection():
    if hasattr(_thread_local, "conn") and _thread_local.conn is not None:
        try:
            _thread_local.conn.close()
        except Exception:
            pass
        _thread_local.conn = None


def build_vision_prompt(user_message: str, vision_context: Optional[Dict[str, Any]]) -> str:
    if not vision_context:
        return user_message

    faces_data = vision_context.get("faces", [])
    gesture_data = vision_context.get("gesture", {})
    emotion_data = vision_context.get("emotion", {})
    objects_data = vision_context.get("objects", {})
    scene_data = vision_context.get("scene", {})
    obstacle_data = vision_context.get("obstacle", {})

    parts = []

    if faces_data:
        count = len(faces_data)
        parts.append(f"شايف {count} شخص قدامي")

    obj_list = objects_data.get("objects", [])
    if obj_list:
        labels = [o.get("label", "") for o in obj_list if o.get("label")]
        if labels:
            parts.append(f"شايف: {', '.join(labels[:5])}")

    scene_desc = scene_data.get("scene_description", "")
    if scene_desc:
        parts.append(f"المكان: {scene_desc[:60]}")

    emotion = emotion_data.get("emotion", "")
    if emotion and emotion not in ("neutral", "", "none"):
        parts.append(f"الشخص يبدو: {emotion}")

    gesture = gesture_data.get("gesture", "")
    if gesture and gesture not in ("none", "", "unknown"):
        parts.append(f"حركة يد: {gesture}")

    if obstacle_data.get("obstacle_detected"):
        direction = obstacle_data.get("direction", "")
        parts.append(f"في عائق {direction}")

    if not parts:
        return user_message

    vision_line = "ما تشوفه الكاميرا دلوقتي: " + " | ".join(parts)
    if user_message:
        return f"{vision_line}\n\nسؤال الطالب: {user_message}"
    return vision_line


class OpenRouterConnection:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        chat_timeout_seconds: Optional[int] = None,
        availability_timeout_seconds: Optional[int] = None,
    ):
        self.api_key = api_key or _LLM.openrouter_api_key
        self.model = model or _LLM.openrouter_model
        self.chat_timeout = (chat_timeout_seconds or _LLM.request_timeout_seconds)
        self.avail_timeout = (availability_timeout_seconds or _LLM.openrouter_availability_timeout_seconds)
        self.base_url = "https://openrouter.ai/api/v1"

        if not self.api_key:
            logger.warning(
                "[LLM] No API key configured. "
                "Set ROBOT_OPENROUTER_API_KEY env variable. "
                "Running in offline mode."
            )

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            r = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.avail_timeout,
            )
            return r.status_code == 200
        except Exception as e:
            logger.error(f"[LLM] OpenRouter not reachable: {e}")
            return False

    def chat(self, messages: List[dict], timeout: Optional[int] = None) -> str:
        if not self.api_key:
            raise LLMModuleError(
                "[llm] OpenRouter API key not configured."
            )

        timeout = timeout or self.chat_timeout
        retries = 3
        last_exc = None

        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json={"model": self.model, "messages": messages},
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout,
                )

                if response.status_code == 429 or response.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("[LLM] HTTP %d, retry %d/%d after %ds",
                                   response.status_code, attempt + 1, retries, wait)
                    time.sleep(wait)
                    continue

                if response.status_code != 200:
                    raise LLMModuleError(
                        f"[llm] OpenRouter returned {response.status_code}: {response.text[:200]}"
                    )

                content = (
                    response.json()
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                if not content:
                    raise LLMModuleError("[llm] Empty response from OpenRouter")

                return content

            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning("[LLM] Attempt %d/%d failed: %s, retry in %ds",
                               attempt + 1, retries, type(e).__name__, wait)
                if attempt < retries - 1:
                    time.sleep(wait)
                continue
            except LLMModuleError:
                raise
            except Exception as e:
                raise LLMModuleError(f"[llm] Unexpected error: {e}") from e

        raise LLMModuleError(
            "[llm] OpenRouter unavailable after %d retries. "
            "Switching to offline mode." % retries
        )


class SessionManager:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _SETTINGS.paths.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = _get_db_connection(self.db_path)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id   TEXT PRIMARY KEY,
                    student_name TEXT NOT NULL,
                    language     TEXT NOT NULL,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id    TEXT NOT NULL,
                    summary_text  TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );
            """)
            logger.info("[LLM] Database ready (WAL mode)")
        except Exception as e:
            raise LLMModuleError(f"[llm] DB init failed: {e}") from e

    def create_session(self, student_name: str, language: Optional[str] = None) -> str:
        if not student_name:
            raise LLMModuleError("[llm] student_name must be a non-empty string")
        language = language or _SETTINGS.general.default_session_language
        if language not in ("ar", "en"):
            raise LLMModuleError("[llm] language must be 'ar' or 'en'")
        session_id = f"{student_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            conn = _get_db_connection(self.db_path)
            conn.execute(
                "INSERT INTO sessions (session_id, student_name, language) VALUES (?,?,?)",
                (session_id, student_name, language)
            )
            conn.commit()
            logger.info(f"[LLM] Session created: {session_id}")
            return session_id
        except Exception as e:
            raise LLMModuleError(f"[llm] create_session DB error: {e}") from e

    def add_message(self, session_id: str, role: str, content: str) -> int:
        if role not in ("user", "assistant"):
            raise LLMModuleError("[llm] role must be 'user' or 'assistant'")
        if not content:
            raise LLMModuleError("[llm] content must be non-empty")
        try:
            conn = _get_db_connection(self.db_path)
            cursor = conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
                (session_id, role, content)
            )
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            raise LLMModuleError(f"[llm] add_message DB error: {e}") from e

    def get_sliding_window(self, session_id: str, window_size: int = 10) -> List[dict]:
        try:
            conn = _get_db_connection(self.db_path)
            rows = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
                (session_id, window_size)
            ).fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
        except Exception as e:
            raise LLMModuleError(f"[llm] get_sliding_window DB error: {e}") from e

    def get_full_history(self, session_id: str) -> List[dict]:
        try:
            conn = _get_db_connection(self.db_path)
            rows = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id=? ORDER BY timestamp ASC",
                (session_id,)
            ).fetchall()
            return [{"role": r[0], "content": r[1]} for r in rows]
        except Exception as e:
            raise LLMModuleError(f"[llm] get_full_history DB error: {e}") from e

    def get_message_count(self, session_id: str) -> int:
        try:
            conn = _get_db_connection(self.db_path)
            return conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
            ).fetchone()[0]
        except Exception as e:
            raise LLMModuleError(f"[llm] get_message_count DB error: {e}") from e

    def save_summary(self, session_id: str, summary_text: str, message_count: int):
        try:
            conn = _get_db_connection(self.db_path)
            conn.execute(
                "INSERT INTO summaries (session_id, summary_text, message_count) VALUES (?,?,?)",
                (session_id, summary_text, message_count)
            )
            conn.commit()
            logger.info(f"[LLM] Summary saved ({message_count} messages)")
        except Exception as e:
            raise LLMModuleError(f"[llm] save_summary DB error: {e}") from e

    def get_session_language(self, session_id: str) -> str:
        try:
            conn = _get_db_connection(self.db_path)
            result = conn.execute(
                "SELECT language FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            return result[0] if result else _SETTINGS.general.default_session_language
        except Exception:
            return _SETTINGS.general.default_session_language

    def close_connections(self):
        _close_db_connection()


class MemoryManager:
    def __init__(
        self,
        session_manager: SessionManager,
        openrouter: OpenRouterConnection,
        window_size: Optional[int] = None,
    ):
        self.session_manager = session_manager
        self.openrouter = openrouter
        self.window_size = int(window_size or _LLM.sliding_window_size)

    def should_summarize(self, session_id: str) -> bool:
        return self.session_manager.get_message_count(session_id) >= self.window_size

    def summarize(self, session_id: str) -> Optional[str]:
        history = self.session_manager.get_full_history(session_id)
        language = self.session_manager.get_session_language(session_id)
        if not history:
            return None
        conv_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
        prompt = (
            f"لخص المحادثة التعليمية التالية بإيجاز:\n\n{conv_text}\n\nالملخص:"
            if language == "ar"
            else f"Summarize this educational conversation concisely:\n\n{conv_text}\n\nSummary:"
        )
        try:
            logger.info("[LLM] Summarizing...")
            summary = self.openrouter.chat(
                [{"role": "user", "content": prompt}],
                timeout=_LLM.summarization_timeout_seconds,
            )
            if summary:
                self.session_manager.save_summary(session_id, summary, len(history))
            return summary
        except Exception as e:
            logger.error(f"[LLM] Summarization failed: {e}")
            return None


class LLMModule:
    def __init__(
        self,
        backend: Optional[OpenRouterConnection] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        self.openrouter = backend or OpenRouterConnection()
        self.session_manager = session_manager or SessionManager()
        self.memory_manager = MemoryManager(self.session_manager, self.openrouter)

    def create_session(self, student_name: str, language: Optional[str] = None) -> str:
        return self.session_manager.create_session(student_name, language)

    def is_ready(self) -> bool:
        return self.openrouter.is_available()

    def chat(
        self,
        session_id: str,
        user_message: str,
        vision_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not user_message and not vision_context:
            raise LLMModuleError("[llm.chat] user_message and vision_context cannot both be empty")

        language = self.session_manager.get_session_language(session_id)
        if language == "ar":
            system_content = (
                _SETTINGS.llm.system_prompt_arabic
                + "\n\nقواعد إلزامية يجب الالتزام بها دائماً دون استثناء:\n"
                + "1) تحدث باللغة العربية الفصحى البسيطة والواضحة فقط، حتى لو كان السؤال بلغة أخرى.\n"
                + "2) لا تستخدم أي رمز تعبيري (إيموجي)، ولا أي رموز خاصة، ولا علامات نجمية أو تنسيق Markdown.\n"
                + "3) لا تستخدم أي كلمة أو حرف إنجليزي إطلاقاً، إلا إذا كان اسم علم لا يوجد له مقابل عربي شائع.\n"
                + "4) اجعل إجابتك في جملة أو جملتين فقط، بأسلوب بسيط يفهمه طفل في المرحلة الابتدائية.\n"
                + "5) تجنب التعقيد والحشو والمقدمات الطويلة، وادخل في صلب الإجابة مباشرة.\n"
                + "6) إذا لم تكن متأكداً من الإجابة، قل بوضوح وبساطة إنك لا تعرف، ولا تختلق معلومات.\n"
                + "7) حافظ على نبرة ودودة، مشجعة، وهادئة تناسب التحدث مع طالب صغير."
            )
        else:
            system_content = (
                _SETTINGS.llm.system_prompt_english
                + "\n\nMandatory rules, never break them:\n"
                + "1) Reply only in simple, clear English, even if the question is in another language.\n"
                + "2) No emoji, no special symbols, no markdown formatting.\n"
                + "3) Keep the answer to one or two short sentences, simple enough for a young student.\n"
                + "4) Avoid long introductions — answer directly.\n"
                + "5) If unsure of the answer, say so clearly instead of guessing.\n"
                + "6) Keep a friendly, warm, encouraging tone suitable for a child."
            )

        final_message = build_vision_prompt(user_message, vision_context)
        logger.info("[LLM] vision_context=%s", vision_context)
        logger.info("[LLM] final_message=%s", final_message)
        self.session_manager.add_message(session_id, "user", user_message or "[vision update]")

        history = self.session_manager.get_sliding_window(
            session_id, window_size=self.memory_manager.window_size
        )

        messages = [
            {"role": "system", "content": system_content},
            *history,
            {"role": "user", "content": "[تذكير: ردك لازم يكون بالعربية العامية المصرية فقط]" if language == "ar" else "[Reminder: Reply in English only]"},
            {"role": "assistant", "content": "حسناً، سأرد باللغة العربية الفصحى." if language == "ar" else "Sure, I will reply in English only."},
            {"role": "user", "content": final_message},
        ]

        logger.info(f"[LLM] Sending to OpenRouter (lang={language}, vision={bool(vision_context)})")
        t0 = datetime.now()
        response = self.openrouter.chat(messages)
        elapsed = (datetime.now() - t0).total_seconds()
        logger.info(f"[LLM] Response received in {elapsed:.1f}s: {response[:200]}")

        self.session_manager.add_message(session_id, "assistant", response)

        if self.memory_manager.should_summarize(session_id):
            logger.info("[LLM] Summarization threshold reached")
            self.memory_manager.summarize(session_id)

        return response

    def close(self):
        self.session_manager.close_connections()
