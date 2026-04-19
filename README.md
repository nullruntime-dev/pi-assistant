# Pi Assistant

Voice assistant for Raspberry Pi. Wake word → STT → LLM → TTS.

Quick start: `./install.sh`, edit `.env` with your `GOOGLE_API_KEY`, then reboot.

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
