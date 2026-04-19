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
