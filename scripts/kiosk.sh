#!/bin/bash
# Kiosk mode launcher for Pi Assistant
# Waits for backend, then opens Chromium in fullscreen

# Wait for backend to be ready
echo "Waiting for Pi Assistant backend..."
for i in {1..30}; do
    if curl -s http://localhost:9091/ > /dev/null 2>&1; then
        echo "Backend ready!"
        break
    fi
    sleep 2
done

# Hide cursor
unclutter -idle 0.1 -root &

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Launch Chromium in kiosk mode
chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --no-first-run \
    --start-fullscreen \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000 \
    http://localhost:9091
