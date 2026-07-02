# ROPE Mobile Team — Implementation Tasks

> **Version:** 1.0  
> **Audience:** Mobile Application Development Team  
> **Goal:** Build a companion mobile app compatible with the ROPE educational robot backend.

---

## 1. Overview

The mobile app is a **companion** to the ROPE robot. It does **not** control the robot directly. Its primary role is to deliver academic lesson content to the robot and allow text-based Q&A. The robot handles voice interaction, vision, movement, and all AI processing internally.

**Key constraint:** The robot is fully autonomous and functions without the mobile app. The mobile app enhances the academic experience only.

---

## 2. Required Features

| # | Feature | Backend Ready? |
|---|---------|----------------|
| 1 | PDF Upload | **Future backend work** — no endpoint exists |
| 2 | PDF List / Management | **Future backend work** — no endpoint exists |
| 3 | Academic Mode (set lesson context) | **Ready** — `POST /context` |
| 4 | AI Chat (text Q&A) | **Ready** — `POST /ask` |
| 5 | Academic Status | **Ready** — `GET /status` |
| 6 | Clear Lesson Context | **Ready** — `DELETE /context` |
| 7 | Remote Shutdown | **Ready** — `POST /shutdown` on port 8000 |
| 8 | Shutdown Status | **Ready** — `GET /shutdown-status` on port 8000 |
| 9 | Settings Screen | Client-side only |

---

## 3. PDF AI Module

**This functionality does not exist on the backend yet.**

The robot has no PDF upload, storage, or processing endpoint. The `academic/context.py` module stores only a single text string — it has no PDF parsing or file management.

### Current Backend Behavior

The `POST /context` endpoint accepts **raw lesson text** in the request body. There is no file upload, no PDF extraction, no persistent storage of documents.

### What the Mobile Team Must Do

Because there is no backend PDF endpoint, the mobile app must:

1. **Handle PDF locally** — parse PDF files on-device using a mobile PDF library
2. **Extract text** — convert PDF to plain text on the mobile device
3. **Send extracted text** — pass the extracted text to `POST /context` as the `context` field
4. **Manage PDF list locally** — store PDF metadata (filename, date, preview) in local device storage

### Example Flow (Client-Only PDF Handling)

```text
1. User taps "Upload PDF"
2. Mobile app opens file picker
3. App parses PDF into plain text (on-device)
4. App sends text to POST /context
5. App stores PDF metadata locally
```

> **Future Backend Implementation:** A PDF upload endpoint (`POST /pdf`) and list endpoint (`GET /pdfs`) should be added to the backend to allow server-side storage and management of lesson documents.

---

## 4. Academic Mode

### 4.1 Enable Academic Mode (Set Lesson Context)

Send lesson content to the robot so it can answer student questions.

**Endpoint:** `POST /context`

**URL:** `http://<robot-ip>:8001/context`

**Headers:** `Content-Type: application/json`

**Request Body:**

```json
{
  "context": "Photosynthesis is the process by which plants convert sunlight into energy...",
  "language": "en",
  "lesson_title": "Photosynthesis - Chapter 3"
}
```

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `context` | string | Yes | — | Full lesson text (non-empty) |
| `language` | string | No | `"en"` | `"ar"` or `"en"` |
| `lesson_title` | string | No | `""` | Displayed in `/status` |

**Success Response `200`:**

```json
{ "status": "ok" }
```

**Error `400`:**

```json
{ "detail": "context must be non-empty" }
```

### 4.2 Disable Academic Mode

Clear the active lesson context from the robot's memory.

**Endpoint:** `DELETE /context`

**URL:** `http://<robot-ip>:8001/context`

**Success Response `200`:**

```json
{ "status": "ok" }
```

### 4.3 Current Status

Check whether academic mode is active and get the lesson title.

**Endpoint:** `GET /status`

**URL:** `http://<robot-ip>:8001/status`

**Success Response `200`:**

```json
{
  "active": true,
  "title": "Photosynthesis - Chapter 3"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `active` | boolean | Whether context is currently loaded |
| `title` | string or null | Lesson title, or null if no context |

### 4.4 Important Note

The `POST /ask` endpoint **also sets the lesson context** before answering. This means:

- Use `POST /context` if you want the student to ask follow-up questions via **voice** (the robot's voice pipeline reads from the same `AcademicContext`)
- Use `POST /ask` for a one-shot Q&A that also updates the context

For the best student experience: call `POST /context` first, then let the student ask follow-up questions by speaking to the robot.

---

## 5. AI Chat API

All endpoints are on port **8001** unless noted.

### 5.1 POST /ask

Send a question to the robot's LLM using the provided lesson context. The robot will **speak the answer aloud** and return it in the response.

**URL:** `http://<robot-ip>:8001/ask`

**Method:** `POST`

**Headers:** `Content-Type: application/json`

**Request Body:**

```json
{
  "context": "Photosynthesis is the process by which plants convert sunlight into energy.",
  "question": "What do plants produce during photosynthesis?",
  "language": "en",
  "lesson_title": "Photosynthesis"
}
```

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `context` | string | Yes | — | Lesson text (non-empty) |
| `question` | string | Yes | — | Student question (non-empty) |
| `language` | string | No | `"en"` | `"ar"` or `"en"` |
| `lesson_title` | string | No | `""` | Optional lesson title |

**Success Response `200`:**

```json
{
  "answer": "Plants produce glucose and oxygen during photosynthesis."
}
```

**Error `400`:**

```json
{ "detail": "context must be non-empty" }
```

```json
{ "detail": "question must be non-empty" }
```

**Error `503` (LLM unavailable):**

```json
{ "detail": "[llm] OpenRouter unavailable after 3 retries..." }
```

**Side Effects:**

- The answer is spoken through the robot's speaker
- The answer appears in the robot's face speech bubble
- The lesson context is updated with the provided text

### 5.2 GET /status

Already documented in section 4.3.

### 5.3 POST /context

Already documented in section 4.1.

### 5.4 DELETE /context

Already documented in section 4.2.

---

## 6. Shutdown API

The shutdown server runs on port **8000** (separate from the academic API on 8001). It requires a shared secret token for authentication.

### 6.1 Authentication

The token is set in the robot's `.env` file:

```
SHUTDOWN_TOKEN=ropo-shutdown-default-token
```

The mobile app must have the same token configured (typically in the app's settings screen).

### 6.2 Check Shutdown Status

**URL:** `http://<robot-ip>:8000/shutdown-status`

**Method:** `GET`

**Success Response `200`:**

```json
{
  "shutdown": false
}
```

### 6.3 Request Shutdown

Sets a flag that the robot's `shutdown_client.py` detects (polling every 15 seconds) and executes `sudo shutdown -h now`.

**URL:** `http://<robot-ip>:8000/shutdown`

**Method:** `POST`

**Headers:** `Content-Type: application/json`

**Request Body:**

```json
{
  "token": "ropo-shutdown-default-token"
}
```

**Success Response `200`:**

```json
{
  "ok": true,
  "message": "Shutdown requested"
}
```

**Error `403` (bad token):**

```json
{
  "detail": "Unauthorized"
}
```

### 6.4 Reset Shutdown Flag

Cancels a pending shutdown request.

**URL:** `http://<robot-ip>:8000/shutdown-reset`

**Method:** `POST`

**Headers:** `Content-Type: application/json`

**Request Body:**

```json
{
  "token": "ropo-shutdown-default-token"
}
```

**Success Response `200`:**

```json
{
  "ok": true,
  "message": "Shutdown reset"
}
```

### 6.5 Shutdown Flow

```text
1. App sends POST /shutdown with token
2. Robot server sets shutdown_requested = true
3. robot_shutdown_client.py (polling every 15s) detects flag
4. Client sends POST /shutdown-reset to clear flag
5. Client executes: sudo shutdown -h now
6. Robot runs MotorController.stop() + center_servos()
7. Robot powers off completely
```

### 6.6 Safety Notes

- The shutdown takes **up to 15 seconds** to execute (polling interval)
- There is no confirmation that shutdown completed
- The robot's own battery monitor can also trigger shutdown at critical voltage (6.5V)
- After shutdown, the robot will not restart automatically

---

## 7. Configuration

Environment variables relevant to the mobile experience:

| Variable | Default | Description |
|----------|---------|-------------|
| `ROBOT_ACADEMIC_MODE` | `false` | Must be `true` for the API server to start |
| `ROBOT_ACADEMIC_API_PORT` | `8001` | Port for the academic API |
| `ROBOT_DEFAULT_SESSION_LANGUAGE` | `ar` | Default language (`ar` or `en`) |
| `ROBOT_STUDENT_NAME` | `Student` | Student display name |
| `SHUTDOWN_TOKEN` | (empty) | Authentication token for shutdown API |
| `SHUTDOWN_API_URL` | (empty) | Backend URL for shutdown polling |

**For the mobile app:** The user must configure the robot's IP address and shutdown token in the app's settings screen. The academic API port and language are part of the robot's configuration (not mobile-configurable).

---

## 8. Expected Folder Structure

Recommended mobile app architecture:

```text
lib/
├── api/
│   ├── academic_api.dart       # POST /context, DELETE /context, GET /status, POST /ask
│   └── shutdown_api.dart       # GET /shutdown-status, POST /shutdown, POST /shutdown-reset
│
├── models/
│   ├── lesson.dart             # Lesson metadata (title, text, language)
│   ├── chat_message.dart       # Question + answer pair
│   ├── academic_status.dart    # active boolean + title
│   └── shutdown_status.dart    # shutdown boolean
│
├── screens/
│   ├── discovery_screen.dart   # LAN scan or manual IP entry
│   ├── dashboard_screen.dart   # Status + quick actions
│   ├── lesson_screen.dart      # PDF upload / paste lesson text
│   ├── chat_screen.dart        # AI Q&A interface
│   └── settings_screen.dart    # Robot IP, shutdown token, language
│
├── services/
│   ├── pdf_service.dart        # On-device PDF text extraction
│   ├── local_storage.dart      # PDF metadata, conversation history
│   └── http_client.dart        # Shared HTTP client with timeout config
│
├── providers/
│   ├── robot_provider.dart     # Robot connection state
│   ├── lesson_provider.dart    # Active lesson state
│   └── chat_provider.dart      # Chat conversation state
│
└── widgets/
    ├── status_indicator.dart   # Green/red connection dot
    ├── lesson_card.dart        # Lesson preview card
    ├── chat_bubble.dart        # Question/answer bubble
    └── loading_overlay.dart    # Loading states
```

---

## 9. Development Checklist

### Connection & Discovery
- [ ] Screen for entering robot IP address
- [ ] Connection status indicator (online/offline)
- [ ] Automatic reconnect with exponential backoff (5s → 10s → 30s)
- [ ] Timeout handling (no response after 10s)

### PDF / Lesson Management
- [ ] File picker for PDF selection (mobile only)
- [ ] On-device PDF text extraction
- [ ] "Set Lesson" button → `POST /context`
- [ ] "Clear Lesson" button → `DELETE /context`
- [ ] Lesson status display (from `GET /status`)
- [ ] Local storage for PDF metadata list

### AI Chat Screen
- [ ] Text input for questions
- [ ] Send button → `POST /ask`
- [ ] Answer display
- [ ] Loading state while waiting for LLM response
- [ ] Error state for 503 (LLM unavailable)
- [ ] Error state for 400 (invalid input)
- [ ] Connection lost handling

### Shutdown
- [ ] Shutdown button with confirmation dialog
- [ ] Token input in settings
- [ ] Shutdown status polling (optional, every 30s)
- [ ] Visual feedback on success/failure

### Settings Screen
- [ ] Robot IP address field
- [ ] Shutdown token field
- [ ] Language selector (`ar` / `en`)
- [ ] Connection test button (pings `GET /status`)

### Error Handling
- [ ] Network timeout handling
- [ ] JSON parse error handling  
- [ ] "Robot not reachable" screen
- [ ] Retry button on failed requests
- [ ] Graceful degradation when robot is offline

### UI/UX
- [ ] Arabic language support for the app UI
- [ ] English language support for the app UI
- [ ] Loading spinners for all async operations
- [ ] Pull-to-refresh for status
- [ ] Dark/light theme (follow robot's sci-fi aesthetic)

---

## Appendix: API Summary Table

| Method | URL | Port | Purpose | Auth |
|--------|-----|------|---------|------|
| `GET` | `/status` | 8001 | Check academic mode status | None |
| `POST` | `/context` | 8001 | Set lesson context | None |
| `DELETE` | `/context` | 8001 | Clear lesson context | None |
| `POST` | `/ask` | 8001 | Ask question with context | None |
| `GET` | `/shutdown-status` | 8000 | Check shutdown flag | None |
| `POST` | `/shutdown` | 8000 | Request robot shutdown | Token |
| `POST` | `/shutdown-reset` | 8000 | Cancel shutdown | Token |

**Base URL format:** `http://{robot_ip_address}:{port}`
