# Dubora

### AI-Powered Video Translation for Arabic

Dubora is a Windows desktop application that transforms videos into Arabic-subtitled versions using AI.

It handles the complete workflow from extracting audio and transcribing speech to translating subtitle content and rendering the final video — while preserving subtitle timing.

---

## Overview

Dubora was built to turn a multi-step video translation workflow into one desktop application.

Instead of manually:

- extracting audio
- transcribing speech
- creating subtitle files
- translating subtitles
- checking timestamps
- rendering subtitles into the video

Dubora coordinates the entire process automatically.

### Workflow

`Video`
→ `Audio Extraction`
→ `Speech Transcription`
→ `Arabic Translation`
→ `SRT Validation`
→ `Final Video`

---

## Key Features

- AI-powered speech transcription
- Context-aware Arabic subtitle translation
- Preserves original subtitle timestamps
- Automatic audio extraction with FFmpeg
- Automatic subtitle rendering
- Long-video chunk processing
- Translation request retries
- Resume support for interrupted jobs
- Cancelable processing
- Real-time translation progress
- Configurable subtitle font and size
- Configurable output directory
- Processing logs for diagnostics
- Windows desktop interface
- Server-side AI gateway

---

## AI Gateway Architecture

Dubora does not expose AI provider credentials inside the desktop application.

The application communicates with a separate backend gateway:

```text
Dubora Desktop
      ↓
Dubora AI Gateway
      ↓
AI Provider
