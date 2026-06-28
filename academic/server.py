from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_started = False
_server_thread: Optional[threading.Thread] = None


def create_academic_app(academic_context, llm, tts_module, face_module):
    """Build the FastAPI application for academic mode.
    Imported lazily so missing fastapi/uvicorn doesn't break the main robot."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="Rope Academic API", version="1.0.0")

    class AskRequest(BaseModel):
        context: str
        question: str
        language: str = "en"
        lesson_title: str = ""

    class ContextRequest(BaseModel):
        context: str
        language: str = "en"
        lesson_title: str = ""

    @app.get("/status")
    def get_status():
        return {
            "active": academic_context.is_active(),
            "title": academic_context.get_title(),
        }

    @app.post("/context")
    def set_context(body: ContextRequest):
        if not body.context.strip():
            raise HTTPException(status_code=400, detail="context must be non-empty")
        academic_context.set(
            title=body.lesson_title or "Untitled",
            content=body.context,
        )
        logger.info("[academic] /context: title=%r", body.lesson_title)
        return {"status": "ok"}

    @app.delete("/context")
    def delete_context():
        academic_context.clear()
        return {"status": "ok"}

    @app.post("/ask")
    def ask(body: AskRequest):
        if not body.context.strip():
            raise HTTPException(status_code=400, detail="context must be non-empty")
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="question must be non-empty")

        lang = body.language if body.language in ("ar", "en") else "en"

        academic_context.set(
            title=body.lesson_title or "Untitled",
            content=body.context,
        )

        ctx_str = academic_context.get_formatted(lang)

        try:
            response = llm.chat(
                session_id="academic_api",
                user_message=body.question,
                academic_context=ctx_str,
            )
        except Exception as e:
            logger.error("[academic] /ask LLM error: %s", e)
            raise HTTPException(status_code=503, detail=str(e)) from e

        face_module.set_spoken_text(response)

        try:
            tts_module.speak(response, lang)
        except Exception as e:
            logger.warning("[academic] /ask TTS error: %s", e)

        logger.info("[academic] /ask: question=%r answer=%r", body.question[:80], response[:120])
        return {"answer": response}

    return app


def run_academic_server(app, host: str = "0.0.0.0", port: int = 8001) -> Optional[threading.Thread]:
    global _started, _server_thread
    if _started:
        logger.warning("[academic] Server already running on port %d", port)
        return None
    try:
        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True, name="academic-api")
        thread.start()
        _server_thread = thread
        _started = True
        logger.info("[academic] API server started on %s:%d", host, port)
        return thread
    except ImportError:
        logger.warning("[academic] fastapi/uvicorn not installed — academic API disabled")
        return None
    except Exception as e:
        logger.warning("[academic] Failed to start API server: %s", e)
        return None
