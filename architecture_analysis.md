# GPI.exe Architecture Analysis

This document provides a detailed breakdown of the decompiled source code for `GPI.exe`, identifying key components, logic flows, and dependencies.

## Overview
The application is a Python-based GUI tool built with `tkinter` and `tkinterdnd2`. Its primary purpose is to generate AI-assisted prompts from images using the Google Gemini API.

## Core Components

### 1. Main Application (`PromptApp` class)
- **Role:** Orchestrates the UI and coordinates between user input, image processing, and API calls.
- **Key Features:**
    - **API Key Management:** Saves and loads the Gemini API key from `gpi_api_key.txt`.
    - **Image Input Options:** Supports local file selection, clipboard pasting, URL downloads, and drag-and-drop.
    - **Model Selection:** Allows switching between different Gemini models (e.g., `gemini-1.5-flash`, `gemini-1.5-pro`).
    - **Prompt Generation:** Sends images and instructions to the Gemini API and displays the resulting prompt.
    - **History Persistence:** Stores past prompts in `history.txt`.

### 2. Drag-and-Drop System
- **Cross-Platform:** Uses `tkinterdnd2` for standard drag-and-drop.
- **Windows-Specific:** Implements a custom `WindowsDropTarget` using `pywin32` (`pythoncom`, `win32com`) to handle complex OLE drag-and-drop scenarios (e.g., dragging images directly from a web browser).

### 3. Image Processing Logic
- **Module:** Functions like `optimize_image_bytes` and `prepare_image_bytes`.
- **Functionality:**
    - Detects MIME types.
    - Resizes large images (max 1024px on the longest edge).
    - Optimizes image quality and format (JPEG/PNG/WEBP) to reduce payload size.
    - Enforces a 5MB maximum file size.

### 4. Gemini API Integration
- **Endpoints:** Interacts with `https://generativelanguage.googleapis.com/v1beta/models/`.
- **Request Format:** Sends base64-encoded image data along with a system-defined instruction prompt.
- **Streaming Support:** Implements a streaming response handler to display the generated prompt in real-time.

### 5. UI & Design System
- **Styling:** Uses a custom design token system (colors, spacing, typography) applied via `ttk` styles.
- **Layout:** Balanced multi-panel design with a header for input, a central area for settings, and a large output area with history.

## Key Logic Flows

### Prompt Generation Flow
1. User selects/pastes an image.
2. `PromptApp` prepares the image payload (encoding, resizing).
3. `generate_prompt` function is called (optionally with retries).
4. Gemini API is invoked via `POST` request.
5. Response is parsed and displayed in the `output_text` widget.
6. The prompt is saved to local history.

### Drag-and-Drop Flow
1. User drops an item onto the UI.
2. `handle_win_drop` (Windows) or `on_drop` (Standard) captures the event.
3. If it's a file, the path is resolved.
4. If it's a URL, an asynchronous download begins.
5. If it's raw data (virtual file), it's captured in-memory.

## Dependencies
- `tkinter` (Core GUI)
- `tkinterdnd2` (Drag-and-Drop)
- `Pillow` (Image Processing)
- `pywin32` (Windows COM/OLE integration)
- `requests` (API communication - actually uses `urllib.request` in the decompiled code)
- Standard Python libraries: `json`, `base64`, `threading`, `pathlib`.

## Future Rebuild Suggestions
- **Modern UI:** Replace `tkinter` with `CustomTkinter` or `PyQt/PySide` for a more modern native look.
- **Refactoring:** Move API calls and image logic into dedicated service classes.
- **Enhanced Settings:** Add more granular control over Gemini parameters (top-p, top-k, safety settings).
