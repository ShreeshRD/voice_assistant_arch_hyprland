#!/usr/bin/env python3
"""
Offline Chatterbox TTS HTTP Server
===================================
Serves POST /v1/audio/speech  →  raw WAV bytes

Request body (JSON):
  { "input": "<text>", "voice": "<path_or_filename>", "model": "chatterbox" }

The model is loaded once on startup. Subsequent requests are handled
in-process without any model reloading overhead.

Port: 8005 (replaces the Docker chatterbox-tts container)
"""

import argparse
import gc
import io
import json
import logging
import os
import re
import sys
import warnings
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Silence noisy deprecation warnings ─────────────────────────────────────
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*sdpa.*")

# ── Force offline mode before any HF imports ───────────────────────────────
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import torch
import torchaudio as ta
from chatterbox.tts import ChatterboxTTS

# ── Configuration ───────────────────────────────────────────────────────────
PORT = 8005
VOICE_DIR = Path("/home/arch/programs/jarvis_voice")
# DEFAULT_VOICE is set at runtime from --voice CLI argument (see main())
EXAGGERATION = 0.5
MAX_CHUNK_CHARS = 140   # Safe limit for 4 GB VRAM cards

logging.basicConfig(
    level=logging.INFO,
    format="[TTS-Server] %(levelname)s  %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("tts_server")


# ── Text chunking ────────────────────────────────────────────────────────────
def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list:
    """Split text into GPU-safe chunks, preserving sentence boundaries."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    final_chunks = []

    for para in paragraphs:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
        for sentence in sentences:
            if len(sentence) <= max_chars:
                final_chunks.append(sentence)
            else:
                sub_chunks = [s.strip() for s in re.split(r"(?<=,)\s+", sentence) if s.strip()]
                for sub in sub_chunks:
                    if len(sub) <= max_chars:
                        final_chunks.append(sub)
                    else:
                        words = sub.split(" ")
                        current = ""
                        for word in words:
                            if len(current) + len(word) + 1 <= max_chars:
                                current += word + " "
                            else:
                                if current:
                                    final_chunks.append(current.strip())
                                current = word + " "
                        if current:
                            final_chunks.append(current.strip())

    return [c for c in final_chunks if c]


# ── Voice path resolution ────────────────────────────────────────────────────
def resolve_voice(voice_name: str, default_voice: Path) -> Path:
    """
    Resolve a voice identifier to an absolute path:
      1. If it's already a valid absolute path, use it directly.
      2. Search VOICE_DIR for a matching filename (case-insensitive).
      3. Fall back to default_voice (set from --voice CLI arg at startup).
    """
    candidate = Path(voice_name)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    # Search voice directory for a matching filename
    if VOICE_DIR.is_dir():
        for f in VOICE_DIR.iterdir():
            if f.name.lower() == candidate.name.lower():
                return f

    log.warning("Voice '%s' not found; falling back to %s", voice_name, default_voice)
    return default_voice


# ── Model singleton ──────────────────────────────────────────────────────────
def load_model(device: str = "cpu"):
    # TTS is forced to CPU by default so it never competes with the LLM for VRAM.
    # Gemma e2b already occupies ~2838 MiB on a 3.8 GB card; loading Chatterbox
    # on GPU as well causes the llama-server scheduler to OOM and crash.
    # Pass --device cuda via CLI if VRAM budget ever allows it.
    log.info("Loading ChatterboxTTS from local cache on device: %s", device)
    model = ChatterboxTTS.from_pretrained(device=device)
    log.info("Model ready on device: %s", device)
    return model, device


# ── Synthesis ────────────────────────────────────────────────────────────────
def synthesize(model, text: str, voice_path: Path, device: str = "cpu") -> bytes:
    """Generate WAV bytes for *text* cloned from *voice_path*."""
    log.info("Preparing voice conditionals from: %s", voice_path)
    model.prepare_conditionals(str(voice_path), exaggeration=EXAGGERATION)

    chunks = split_text(text)
    log.info("Synthesising %d chunk(s) for %d chars of text", len(chunks), len(text))

    silence_len = int(model.sr * 0.2)
    silence = torch.zeros((1, silence_len))
    audio_parts = []

    for i, chunk in enumerate(chunks):
        log.info("  chunk %d/%d: %r", i + 1, len(chunks), chunk[:60])
        try:
            with torch.no_grad():
                wav = model.generate(chunk, exaggeration=EXAGGERATION).cpu()
            if wav.ndim == 1:
                wav = wav.unsqueeze(0)
            audio_parts.append(wav)
            if i < len(chunks) - 1:
                audio_parts.append(silence)
        except Exception as exc:
            log.error("  chunk %d failed: %s", i + 1, exc)
        finally:
            gc.collect()
            if device == "cuda" and torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

    if not audio_parts:
        raise RuntimeError("All TTS chunks failed — no audio generated")

    final_wav = torch.cat(audio_parts, dim=-1)

    buf = io.BytesIO()
    ta.save(buf, final_wav, model.sr, format="wav")
    buf.seek(0)
    return buf.read()


# ── HTTP handler ─────────────────────────────────────────────────────────────
class TTSHandler(BaseHTTPRequestHandler):
    # All set as class attributes by main() before the server starts
    model = None
    device: str = "cpu"
    default_voice: Path = None  # resolved from --voice CLI arg

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def do_POST(self):
        if self.path != "/v1/audio/speech":
            self._send_error(404, "Not Found")
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            self._send_error(400, f"Invalid JSON: {exc}")
            return

        text = body.get("input", "").strip()
        # Use the per-request voice if provided, otherwise fall back to the
        # server-wide default that was passed via --voice at startup.
        voice_name = body.get("voice") or str(TTSHandler.default_voice)

        if not text:
            self._send_error(400, "Missing 'input' field")
            return

        voice_path = resolve_voice(voice_name, TTSHandler.default_voice)
        log.info("Synthesis request: %d chars, voice=%s", len(text), voice_path.name)

        try:
            wav_bytes = synthesize(TTSHandler.model, text, voice_path, TTSHandler.device)
        except Exception as exc:
            log.error("Synthesis failed: %s", exc)
            self._send_error(500, str(exc))
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        self.end_headers()
        self.wfile.write(wav_bytes)
        log.info("Response sent: %d bytes", len(wav_bytes))

    def _send_error(self, code: int, message: str):
        body = message.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Offline Chatterbox TTS HTTP server")
    parser.add_argument(
        "--voice",
        default=str(VOICE_DIR / "jarvis.wav"),
        help="Default voice file path or filename (resolved against VOICE_DIR)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device to run Chatterbox on (default: cpu to preserve VRAM for LLM)",
    )
    args = parser.parse_args()

    # Resolve the startup voice so we have an absolute path from the start
    startup_voice = resolve_voice(args.voice, VOICE_DIR / "jarvis.wav")
    log.info("Default voice set to: %s", startup_voice)

    TTSHandler.model, TTSHandler.device = load_model(args.device)
    TTSHandler.default_voice = startup_voice

    server = HTTPServer(("127.0.0.1", PORT), TTSHandler)
    log.info("TTS server listening on http://127.0.0.1:%d", PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down TTS server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
