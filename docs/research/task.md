## Summary

### Goal

Build a web app for collecting Edge Impulse training data from the Arduino Nano 33 + OV7675 camera.

### Design Decisions

- **Camera source**: OV7675 via serial bridge (reusing existing `live_camera_view.py` serial protocol)
- **Image format**: Raw 160×120 grayscale PNG (matches model inference input)
- **Architecture**: Flask backend + single-page HTML/JS frontend

### Implementation

Created two files + one launcher script:

1. **`scripts/data_collector.py`** — Python Flask server that:
   - Reads frames from Arduino over serial (OVF1 protocol)
   - Serves live MJPEG preview at `/stream`
   - Saves raw grayscale PNG on `POST /capture`
   - Tracks capture count via `/count`
2. **`scripts/templates/index.html`** — Web frontend with:
   - Live camera preview via `<img src="/stream">`
   - "Take Shot" button
   - Capture counter display
   - Last capture thumbnail
3. **`scripts/collect.sh`** — Launcher script (follows existing `live_view.sh` pattern)

### Usage

```bash
# Plug in Arduino, then:
./scripts/collect.sh
# Open http://localhost:5000
Dependencies added: Flask (installed in .venv)
```
