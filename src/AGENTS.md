# Purpose

The React frontend (`src`) provides the user interface for the Voice Assistant desktop application. It features an interactive, animated visual Orb for voice interaction/status feedback and a multi-tab Settings panel for device selection, model parameters, capabilities toggling, and knowledge base ingestion.

# Ownership

- Primary: Frontend / UI Team
- Scope: `src/` directory, including React components, Vite configuration, styling assets, and frontend-to-Tauri communication logic.

# Local Contracts

- **Framework**: React 19, TypeScript, and Vite.
- **Styling**: TailwindCSS is utilized alongside `App.css` and `index.css` for custom animations, gradients, and a sleek, unified dark glassmorphism aesthetic.
- **Host Communication**: Must use Tauri's `@tauri-apps/api/core` (`invoke`) and `@tauri-apps/api/event` (`listen`) to send commands and receive pipeline updates from the Rust backend.
- **Audio Playback**: Chunks of base64-encoded WAV audio from text-to-speech are played sequentially. Must support immediate cleanup and cancellation via `pipeline_interrupted` and `hotkey_pressed` events.

# Work Guidance

- Keep UI components responsive and interactive.
- Maintain visual feedback mapping:
  - `listening` -> Blue glowing pulse
  - `thinking` / `transcribing` -> Smooth cyan breath/rotation
  - `speaking` -> Dynamic volume-based breathing
  - `tool_call` -> Orange gear rotation
  - `error` -> Red status text and static visual
- Manage bubble history strictly, showing tool-calling status chips ephemerally.

# Verification

- **Development Server**: Run `npm run dev` to start the frontend Vite server.
- **Production Build**: Run `npm run build` to verify type-checking and bundle compilation.

# Child DOX Index

- No child indexes are defined at this level.
