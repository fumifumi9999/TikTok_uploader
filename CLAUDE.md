# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A TikTok video uploader using the TikTok Content Posting API (OAuth 2.0). Three Python files cover auth, upload logic, and a Tkinter GUI.

## Running the tools

```bash
# Authenticate and save tokens to .env (opens browser for OAuth)
python auth.py

# Launch the GUI uploader
python gui.py

# The uploader module can also be imported directly
python -c "from uploader import upload_file; upload_file('1.mp4')"
```

Dependencies are in `.venv/`. Activate with `.venv/Scripts/activate` (Windows) or use `uv run`.

## Architecture

**`auth.py`** — OAuth 2.0 authorization code flow:
- Opens browser to TikTok auth page
- Starts a local HTTP server on port 3000 to receive the redirect callback
- The `REDIRECT_URI` is an ngrok tunnel (`ngrok-free.dev`) — ngrok must be running and forwarding to port 3000
- On success, writes `TIKTOK_ACCESS_TOKEN` and `TIKTOK_REFRESH_TOKEN` to `.env` via `save_env_value()`

**`uploader.py`** — two upload modes:
- `upload_file(path)` — **Inbox mode**: uploads video to the user's TikTok inbox; user manually edits and publishes via the TikTok app. Uses `INIT_API`.
- `go_public(path)` — **Direct Post mode**: publishes immediately with hardcoded `post_info` (title, privacy, etc.) defined at the top of `go_public()`. Uses `DIRECT_POST_API`. Currently `privacy_level = "SELF_ONLY"` (required for unreviewed apps).
- Chunked upload: files ≤64 MB upload as a single chunk; larger files split into 10 MB chunks. TikTok requires `total_chunk_count = floor(file_size / chunk_size)` with the remainder absorbed into the final chunk (up to 128 MB).
- Token expiry is auto-detected on init failure; `refresh_access_token()` is called automatically before retrying.

**`gui.py`** — Tkinter wrapper around `upload_file` and `go_public`. Upload runs in a daemon thread to keep the UI responsive; results are posted back to the main thread via `self.after(0, ...)`.

## Environment

`.env` must contain:
```
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_ACCESS_TOKEN=...    # written by auth.py
TIKTOK_REFRESH_TOKEN=...   # written by auth.py
```

To change post metadata (title, privacy, duet/stitch settings), edit the hardcoded variables at the top of `go_public()` in `uploader.py`.
