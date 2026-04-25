# Pi Assistant

Voice assistant for Raspberry Pi. Wake word → STT → LLM → TTS.

Targets the **Raspberry Pi 5 + official 7" touchscreen (800×480)**. The dashboard is laid out for that resolution; on a desktop browser it just shows a wider version of the same panels.

Quick start:

```bash
./install.sh                                # idempotent — also the upgrade path
nano .env                                   # set GOOGLE_API_KEY (and optionally WEATHER_LAT/LON)
sudo reboot
```

## Audio prerequisites (PipeWire)

The backend writes audio through ALSA → PipeWire. PipeWire on a fresh Bookworm Pi ships with the daemon enabled but the **session manager** (`wireplumber`) and the **PulseAudio compatibility shim** (`pipewire-pulse`) are not. Without them, PipeWire has zero real sinks and TTS gets routed to `auto_null` — i.e. silence.

Enable all three once per machine (no sudo):

```bash
systemctl --user enable --now pipewire pipewire-pulse wireplumber
```

Verify a real sink exists (not `auto_null`):

```bash
pactl list short sinks
# good:  74  bluez_output.XX_XX_XX_XX_XX_XX.1   PipeWire   ...
# bad:   0   auto_null                          module-null-sink.c   ...
```

The `pi-assistant.service` unit declares `After=` and `Wants=` on these three units, so once they're enabled, the backend will always start after they're ready.

## Operations

The backend runs as a **user-level systemd service** named `pi-assistant`. All commands below use `systemctl --user` (no `sudo`).

### Status & logs

```bash
# Is it running?
systemctl --user status pi-assistant

# Live logs
journalctl --user -u pi-assistant -f

# Last 200 lines
journalctl --user -u pi-assistant -n 200 --no-pager
```

### Start / stop / restart

```bash
systemctl --user start   pi-assistant
systemctl --user stop    pi-assistant
systemctl --user restart pi-assistant    # stop + start in one step
```

Use `restart` after changing `.env`, Python code, or any file under `backend/`. The process is long-lived, so code changes do not hot-reload.

### Hot reload (the one-liner)

There is no file-watcher. **One command reloads everything for both backend and frontend changes:**

```bash
systemctl --user restart pi-assistant
```

What that does:

- Backend code under `backend/` is re-imported (the process is replaced).
- The new process mints a fresh `SERVER_ID` and pushes it to all open WebSocket clients on connect — the kiosk JS sees the id changed and calls `window.location.reload()`. So **frontend changes under `frontend/` show up automatically** without touching Chromium.
- Static files are served with `Cache-Control: no-store`, so the browser never returns stale CSS/JS.
- `.env` is re-read by systemd via `EnvironmentFile=`, so changes there take effect on restart too.

If you want to do a full kill from a fresh terminal (e.g. SSH session) without waiting for the WS reload, see the **Kiosk** section below for the manual Chromium controls.

### Reload the service definition

Only needed when `scripts/pi-assistant.service` itself changes (or you edit `~/.config/systemd/user/pi-assistant.service`):

```bash
cp scripts/pi-assistant.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart pi-assistant
```

### Enable / disable autostart at boot

```bash
systemctl --user enable  pi-assistant     # start on boot
systemctl --user disable pi-assistant     # don't start on boot
```

Autostart-at-boot-without-login requires lingering (set once by `install.sh`):

```bash
sudo loginctl enable-linger "$USER"
```

### Upgrade

Pull latest code and refresh dependencies:

```bash
cd ~/pi-assistant
git pull
source .venv/bin/activate
pip install -r requirements.txt
systemctl --user restart pi-assistant
```

If `scripts/pi-assistant.service` changed in the pull, also run the **Reload** steps above.

Re-running `./install.sh` is idempotent and performs the full upgrade path (deps, models, service, kiosk).

### Kiosk (Chromium fullscreen)

The kiosk is a plain Chromium autostart (`~/.config/autostart/kiosk.desktop` → `scripts/kiosk.sh`), not a systemd service.

**Frontend changes auto-reload on backend restart.** The backend mints a new `SERVER_ID` each start and pushes it over the WebSocket; the client reloads when it sees a new id. Static assets also ship with `Cache-Control: no-store`, so no stale JS/CSS. So after editing anything under `frontend/`:

```bash
systemctl --user restart pi-assistant
```

Manual kiosk controls (for cases where the WS auto-reload doesn't fire — e.g. the page hasn't connected yet, or you changed `kiosk.sh` itself):

```bash
# Soft refresh (focus the Pi display, then):
#   Ctrl+Shift+R

# Restart the kiosk process entirely:
pkill -f chromium
~/pi-assistant/scripts/kiosk.sh &

# Stop the kiosk (e.g. while debugging with a normal browser):
pkill -f chromium

# Start it manually (won't auto-relaunch until next login otherwise):
~/pi-assistant/scripts/kiosk.sh &
```

### Run in the foreground (debugging)

Stop the service first so it doesn't fight for the mic / port:

```bash
systemctl --user stop pi-assistant
cd ~/pi-assistant
source .venv/bin/activate
python run.py
```

### Uninstall the service

```bash
systemctl --user disable --now pi-assistant
rm ~/.config/systemd/user/pi-assistant.service
systemctl --user daemon-reload
```

## Configuration (`.env`)

All settings live in `~/pi-assistant/.env` (loaded by systemd via `EnvironmentFile=`). Restart the service after editing.

| Variable | Default | Notes |
| --- | --- | --- |
| `GOOGLE_API_KEY` | _required_ | Gemini API key. |
| `LLM_MODEL` | `gemini-2.5-flash` | Any Gemini chat model id. |
| `WAKE_WORD` | `hey_jarvis` | Any pretrained openWakeWord model name. |
| `WAKE_WORD_THRESHOLD` | `0.4` (in `.env`; code default is `0.6`) | Lower = more sensitive. See **Tuning the wake word** below. |
| `WAKE_WORD_CONSECUTIVE_FRAMES` | `2` | Frames over threshold required to fire. Raise to `3` if you get false wakes despite a low threshold. |
| `STT_MODEL_SIZE` | `tiny.en` | `tiny.en` / `base.en` / `small.en` (CPU cost rises fast). |
| `TTS_VOICE` | `amy` | Piper voice — `amy`, `lessac`, `hfc_female`, `libritts_r`, `ryan_high`. |
| `TTS_LENGTH_SCALE` | `0.8` | <1 = faster speech, >1 = slower. |
| `WEATHER_LAT` | `40.7128` (NYC) | Latitude for the dashboard weather card. |
| `WEATHER_LON` | `-74.0060` (NYC) | Longitude. Open-Meteo, no API key needed. |
| `HOST` / `PORT` | `0.0.0.0` / `9091` | Where the FastAPI server binds. |

### Tuning the wake word

If you have to shout "Hey Jarvis" to get a response, the openWakeWord score is clearing the threshold but only barely. Watch live scores:

```bash
journalctl --user -u pi-assistant -f | grep -i 'wake word detected'
# Wake word detected: 'hey_jarvis' (score: 0.87)
```

If your usable scores cluster around 0.5–0.8, the default code threshold of 0.6 is too strict. Tune via `.env`:

| Symptom | Try |
| --- | --- |
| Have to shout / move closer to the mic | Lower `WAKE_WORD_THRESHOLD` to `0.4`, then `0.3` |
| Random TV / conversation triggers it | Raise `WAKE_WORD_THRESHOLD` to `0.5`+ **or** raise `WAKE_WORD_CONSECUTIVE_FRAMES` to `3` |
| Mic gain seems low first | `amixer -c 0 sset 'Mic' 100%` (USB PnP capture) before lowering the threshold further |

Restart after changing `.env`:

```bash
systemctl --user restart pi-assistant
```

### Tuning the listen behaviour

If Jarvis cuts you off mid-sentence, or won't stop listening when the TV is on, the relevant knobs are constants near the top of `_listen_and_transcribe` in `backend/audio/pipeline.py`:

| Constant | Default | Effect of raising it |
| --- | --- | --- |
| `max_silence` | `14` (~0.9s) | Longer mid-sentence pauses tolerated before "you're done". |
| `max_duration` | `235` (~15s) | Longer hard cap for a single utterance. |
| `silence_rms = max(0.018, floor × 3.0)` | — | Higher → only louder/closer speech registers. The `× 3.0` multiplier is what rejects background TV; bump to `4.0` if a TV still hijacks the mic. |

The threshold is **adaptive**: the pipeline keeps a rolling 12.8s window of mic RMS and uses the 25th-percentile as the room's noise floor each time it starts listening. So a quiet room and a TV-on room both get a sensible threshold without you tweaking anything. Watch a fresh value print on every wake:

```bash
journalctl --user -u pi-assistant -f | grep '\[vad\]'
# [vad] ambient_floor=0.0061 silence_rms=0.0183     # quiet room
# [vad] ambient_floor=0.0240 silence_rms=0.0720     # TV in background
```

## The dashboard

What's on the screen, top-to-bottom:

- **Header** — large clock (HH:MM), date, and current weather (temp in °F + condition). Bluetooth toggle and state pill on the right.
- **Hero row** — live mic waveform on the left; wake-word ring + confidence on the right.
- **Metrics row** — STT latency, TTS latency, CPU %, SoC temperature.
- **Pipeline strip** — per-stage timing for the last turn (wake → STT → intent → TTS) plus the end-to-end number.
- **Recent commands** — scrollable history of recent transcripts.

While the assistant is non-idle, a **Siri-style glowing border** runs around the screen edge:

- Listening — cyan / indigo / violet
- Thinking — yellow / amber / orange
- Speaking — pink / violet / cyan
- A brief brighter pulse fires the moment the wake word is detected.

The colors are CSS variables in `frontend/css/styles.css` (`body[data-state="..."]`) — change those four hex values per state to retheme.
