# MediaBot Pro — Telegram Bot

A feature-rich Telegram bot for image, PDF, video, and social media processing, built with Python.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Features

### 🖼 Image Tools
- **Resize** — presets (HD, FHD, 4K, square, thumbnail) or custom dimensions / ratio / percentage
- **Convert** — PNG, JPG, WEBP, PDF
- **Compress** — reduce file size to a target KB
- **Increase Size** — inflate file size to a target KB
- **Crop** — presets (1:1, 9:16, 4:5, 16:9, 2:1) or custom ratio
- **Rotate / Flip** — 90°/180°/270° rotation, vertical & horizontal flip
- **Effects** — grayscale, sepia, blur, sharpen, brightness, contrast, vivid, cool, warm, grain
- **Watermark** — add custom text watermark
- **Remove Background** — AI-powered background removal (via rembg)
- **OCR** — extract text from images (via Tesseract)
- **EXIF** — view or strip EXIF metadata
- **Auto Color** — automatic color enhancement
- **Add Border** — add a white border around images
- **Collage** — grid, horizontal, or vertical collage from 2+ images
- **Batch Processing** — collect up to 10 images and resize, compress, grayscale, or collage them in one go

### 📄 PDF Tools
- **Compress** — lossless stream compression + lossy JPEG re-render fallback
- **Merge** — combine multiple PDFs into one
- **Split** — split PDF into individual pages
- **Encrypt / Decrypt** — password-protect or remove password
- **Rotate Pages** — 90°, 180°, 270°
- **Watermark** — diagonal text watermark across every page
- **Extract Text** — plain text extraction (with pdfplumber fallback)
- **Extract Tables → CSV** — extract tabular data as CSV
- **PDF → JPG** — convert each page to JPEG
- **Image → PDF** — convert a single image to PDF
- **Info** — page count, file size, metadata, encryption status

### 🎬 Video / GIF
- **Video → GIF** — convert MP4 videos to animated GIFs (max 8s, resized to 480px)

### 📥 Social Media Downloader
- Download media from **Pinterest**, **Instagram**, **TikTok**, **YouTube Shorts**, **Twitter / X**
- Powered by yt-dlp with platform-specific fallbacks

### 🔲 QR Code Generator
- Generate QR codes from text or URLs (with error correction)

---

## Commands

| Command  | Description |
|----------|-------------|
| `/start` | Show the main menu with all available tools |
| `/help`  | List all features |

Simply send an image, PDF, video, or a supported social media link, then choose an action from the inline buttons.

---

## Deployment

The bot is configured to deploy on **Railway** using the provided files:

- `Procfile` — `worker: python bot.py`
- `nixpacks.toml` — system dependencies (tesseract-ocr, poppler-utils, libgl1)
- `apt-packages.txt` — additional packages (poppler-utils, ffmpeg)
- `runtime.txt` — Python 3.12.0

### Environment Variables

| Variable | Description |
|----------|-------------|
| `TOKEN`  | Your Telegram Bot API token |

### Optional Dependencies

Edit `requirements.txt` to enable optional features:

| Library    | Feature                 | Notes |
|------------|-------------------------|-------|
| qrcode     | QR code generation      | Enabled by default |
| pytesseract| OCR (text extraction)   | Requires `tesseract-ocr` system package |
| rembg      | Background removal      | Downloads ~170 MB AI model on first run |
| pdfplumber | Table extraction from PDF| Better text extraction fallback |

---

## License

[MIT](LICENSE)
