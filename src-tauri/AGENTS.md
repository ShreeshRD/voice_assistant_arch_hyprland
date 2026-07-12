# Purpose

The Rust/Tauri backend (`src-tauri`) manages the systems-level logic, audio processing pipeline, AI orchestration, command execution sandboxing, local vector database (RAG), and operating system integrations.

# Ownership

- Primary: Systems / Backend Team
- Scope: `src-tauri/` directory, including Rust source files (`src/`), configuration (`tauri.conf.json`, `Cargo.toml`), and sandboxing containers.

# Local Contracts

- **Language & Framework**: Rust (current edition 2021) and Tauri v2.
- **AI Orchestration**: Integration with Ollama for chat completions, embeddings generation, and screenshot vision descriptions.
- **Audio Capturing**: Using `cpal` to record input samples at appropriate frequencies and feeding them to Whisper-rs for local transcription.
- **Sandbox Security**: Any shell execution requested by the LLM must pass through the sandbox (`sandbox.rs`) validation using either Guarded environment checks or a Docker container isolation boundary.
- **RAG SQLite Store**: Document embeddings are saved into SQLite vectors, supporting insertion and cosine similarity searches locally.
- **Offline TTS Server**: `src/tts_server.py` is a Python HTTP server (port 8005) that loads ChatterboxTTS locally (CUDA → CPU fallback) and serves `POST /v1/audio/speech` requests with raw WAV bytes. `lib.rs` spawns it as a child process on startup (stored in `TTS_PROCESS` static) and kills it on `RunEvent::Exit`. The Rust synthesis path in `voice.rs` is unchanged and continues to POST to `http://localhost:8005/v1/audio/speech`.

# Work Guidance

- Avoid blocking the main Tauri event loop; run heavy AI/audio processing pipelines within Tokio task threads.
- Keep TTS generation streamed via `play_audio_chunk` and coordinate cancellation checks inside loops using `CancellationToken`.
- Do not bypass `sandbox.rs` command verification rules when implementing or extending shell operations.
- When modifying `tts_server.py`, ensure the server still binds `127.0.0.1:8005` and responds with raw `audio/wav` bytes — the Rust client in `voice.rs` has no knowledge of the Python implementation.

# Verification

- **Format & Lints**: Run `cargo fmt` and `cargo clippy`.
- **Application Run**: Run `npm run tauri dev` or `cargo tauri dev` to test the build and run the voice assistant interface.
- **TTS Server**: After `npm run tauri dev`, confirm `[TTS] Python TTS server started (pid ...)` appears in the console and that speaking triggers offline cloned-voice synthesis from `/home/arch/programs/jarvis_voice/jarvis.wav`.

# Child DOX Index

- No child indexes are defined at this level.
