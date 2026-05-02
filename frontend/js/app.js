/**
 * Pi Assistant — voice pipeline dashboard.
 * Subscribes to /ws and renders waveform, wake-word ring, latency cards,
 * pipeline strip, and recent-command log.
 */

const WAVEFORM_BARS = 50;
const WAKE_RING_CIRCUMFERENCE = 528; // matches r=84 in the SVG

class Dashboard {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.serverId = undefined;
        this.state = 'idle';
        this.lastUtterance = '';
        this.utteranceStart = 0;
        this.recentCommands = [];

        this.el = {
            nowTime: document.getElementById('now-time'),
            nowDate: document.getElementById('now-date'),
            nowTemp: document.getElementById('now-temp'),
            nowDesc: document.getElementById('now-desc'),
            statusPill: document.getElementById('status-pill'),
            statusText: document.getElementById('status-text'),
            waveform: document.getElementById('waveform'),
            micDb: document.getElementById('mic-db'),
            utterance: document.getElementById('utterance'),
            duration: document.getElementById('duration'),
            wakeArc: document.getElementById('wake-arc'),
            wakeConf: document.getElementById('wake-conf'),
            sttMs: document.getElementById('stt-ms'),
            sttFoot: document.getElementById('stt-foot'),
            ttsMs: document.getElementById('tts-ms'),
            ttsFoot: document.getElementById('tts-foot'),
            cpuPct: document.getElementById('cpu-pct'),
            cpuFoot: document.getElementById('cpu-foot'),
            tempC: document.getElementById('temp-c'),
            tempFoot: document.getElementById('temp-foot'),
            ppWake: document.getElementById('pp-wake'),
            ppStt: document.getElementById('pp-stt'),
            ppIntent: document.getElementById('pp-intent'),
            ppTts: document.getElementById('pp-tts'),
            e2e: document.getElementById('e2e'),
            recentList: document.getElementById('recent-list'),
            btToggle: document.getElementById('bt-toggle'),
            btBadge: document.getElementById('bt-badge'),
            btPanel: document.getElementById('bt-panel'),
            btList: document.getElementById('bt-list'),
            btScan: document.getElementById('bt-scan'),
            btScanLabel: document.getElementById('bt-scan-label'),
            btRefresh: document.getElementById('bt-refresh'),
            btError: document.getElementById('bt-error'),
            btSub: document.getElementById('bt-sub'),
        };

        this.bluetooth = new BluetoothPanel(this.el);
        this.volume = new VolumeControl();
        this.buildWaveform();
        this.connect();

        // Tick the duration ticker + recent-command "x ago" labels.
        setInterval(() => this.tickRelative(), 1000);

        // Glanceable clock + weather.
        this.tickClock();
        setInterval(() => this.tickClock(), 1000);
        this.refreshWeather();
        setInterval(() => this.refreshWeather(), 10 * 60 * 1000);
    }

    tickClock() {
        const now = new Date();
        const hh = String(now.getHours()).padStart(2, '0');
        const mm = String(now.getMinutes()).padStart(2, '0');
        this.el.nowTime.textContent = `${hh}:${mm}`;
        this.el.nowDate.textContent = now.toLocaleDateString(undefined, {
            weekday: 'short', month: 'short', day: 'numeric'
        });
    }

    async refreshWeather() {
        try {
            const res = await fetch('/api/weather');
            if (!res.ok) return;
            const data = await res.json();
            if (data.error) return;
            const t = (typeof data.temp_f === 'number') ? `${data.temp_f}°F` : '—°F';
            this.el.nowTemp.textContent = t;
            this.el.nowDesc.textContent = data.description || '';
        } catch (_) {
            // Network blip — keep previous values.
        }
    }

    buildWaveform() {
        const frag = document.createDocumentFragment();
        for (let i = 0; i < WAVEFORM_BARS; i++) {
            const bar = document.createElement('div');
            bar.className = 'bar';
            frag.appendChild(bar);
        }
        this.el.waveform.appendChild(frag);
        this.bars = Array.from(this.el.waveform.querySelectorAll('.bar'));
    }

    // ===== WebSocket =====
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
        this.ws.onopen = () => { this.reconnectAttempts = 0; };
        this.ws.onmessage = (e) => {
            try { this.handle(JSON.parse(e.data)); }
            catch (err) { console.warn('bad ws msg', err); }
        };
        this.ws.onclose = () => this.scheduleReconnect();
        this.ws.onerror = () => {};
    }

    scheduleReconnect() {
        const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 15000);
        this.reconnectAttempts++;
        setTimeout(() => this.connect(), delay);
    }

    handle(msg) {
        switch (msg.type) {
            case 'server_id': return this.handleServerId(msg.id);
            case 'state':     return this.setState(msg.state);
            case 'transcript': return this.setTranscript(msg.text, msg.label);
            case 'mic':       return this.setMic(msg);
            case 'wake':      return this.flashWake(msg.score);
            case 'metrics':   return this.applyMetrics(msg);
            // Ignore music/weather — not part of dashboard view.
        }
    }

    handleServerId(id) {
        if (this.serverId === undefined) { this.serverId = id; return; }
        if (id !== this.serverId) window.location.reload();
    }

    // ===== State pill =====
    setState(state) {
        this.state = state;
        const labels = { idle: 'Idle', listening: 'Listening', thinking: 'Processing', speaking: 'Speaking' };
        this.el.statusPill.dataset.state = state;
        this.el.statusText.textContent = labels[state] || state;
        document.body.dataset.state = state;
        if (state === 'listening') {
            this.utteranceStart = Date.now();
        }
        if (state === 'idle') {
            this.utteranceStart = 0;
            this.el.duration.textContent = '';
        }
    }

    setTranscript(text, label) {
        if (label === 'You said' && text) {
            this.lastUtterance = text;
            this.el.utterance.textContent = `"${text}"`;
        }
    }

    // ===== Waveform =====
    setMic(msg) {
        if (typeof msg.db === 'number') {
            this.el.micDb.textContent = `${Math.round(msg.db)} dB`;
        }
        const levels = msg.levels || [];
        // Right-align the latest sample at the rightmost bar.
        for (let i = 0; i < this.bars.length; i++) {
            const idx = levels.length - this.bars.length + i;
            const v = idx >= 0 ? levels[idx] : 0;
            const pct = Math.max(4, Math.min(100, v * 100));
            this.bars[i].style.height = `${pct}%`;
        }
    }

    // ===== Wake word =====
    flashWake(score) {
        const conf = Math.max(0, Math.min(1, score || 0));
        const offset = WAKE_RING_CIRCUMFERENCE * (1 - conf);
        this.el.wakeArc.setAttribute('stroke-dashoffset', offset);
        this.el.wakeConf.textContent = `${conf.toFixed(2)} conf`;

        // Bright pulse on the screen-edge glow at the moment of detection.
        document.body.classList.remove('ai-wake');
        // Force reflow so the animation restarts on rapid re-triggers.
        void document.body.offsetWidth;
        document.body.classList.add('ai-wake');
        clearTimeout(this._wakePulseTimer);
        this._wakePulseTimer = setTimeout(() => {
            document.body.classList.remove('ai-wake');
        }, 900);

        clearTimeout(this._wakeResetTimer);
        this._wakeResetTimer = setTimeout(() => {
            this.el.wakeArc.setAttribute('stroke-dashoffset', WAKE_RING_CIRCUMFERENCE);
        }, 4000);
    }

    // ===== Metrics snapshot =====
    applyMetrics(m) {
        // STT
        if (m.stt_ms > 0) {
            this.el.sttMs.textContent = m.stt_ms;
            const d = m.stt_delta_pct;
            const foot = this.el.sttFoot;
            foot.classList.remove('delta-good', 'delta-bad');
            if (d === null || d === undefined) {
                foot.textContent = 'whisper · int8';
            } else if (d <= -5) {
                foot.classList.add('delta-good');
                foot.textContent = `${Math.abs(d)}% vs base`;
            } else if (d >= 5) {
                foot.classList.add('delta-bad');
                foot.textContent = `${d}% vs base`;
            } else {
                foot.textContent = 'on baseline';
            }
        }

        // TTS
        if (m.tts_ms > 0) {
            this.el.ttsMs.textContent = m.tts_ms;
            this.el.ttsFoot.textContent = 'piper · amy-low';
        }

        // System
        if (m.system) {
            const s = m.system;
            if (typeof s.cpu_pct === 'number') {
                this.el.cpuPct.textContent = Math.round(s.cpu_pct);
            }
            const cores = s.cores ? `${s.cores} cores` : '— cores';
            const freq = s.freq_ghz ? ` · ${s.freq_ghz.toFixed(1)} GHz` : '';
            this.el.cpuFoot.textContent = `${cores}${freq}`;

            if (typeof s.temp_c === 'number') {
                this.el.tempC.textContent = Math.round(s.temp_c);
                const foot = this.el.tempFoot;
                foot.classList.remove('warn');
                if (s.thermal === 'throttling') foot.classList.add('warn');
                foot.textContent = s.thermal || '—';
            } else {
                this.el.tempC.textContent = '—';
                this.el.tempFoot.textContent = 'sensor unavailable';
            }
        }

        // Pipeline strip
        if (m.wake_ms) this.el.ppWake.textContent = `${m.wake_ms}ms`;
        if (m.stt_ms) this.el.ppStt.textContent = `${m.stt_ms}ms`;
        if (m.intent_ms) this.el.ppIntent.textContent = `${m.intent_ms}ms`;
        if (m.tts_ms) this.el.ppTts.textContent = `${m.tts_ms}ms`;
        if (m.e2e_ms) this.el.e2e.textContent = `${(m.e2e_ms / 1000).toFixed(2)}s`;

        // Recent commands
        if (Array.isArray(m.recent)) {
            this.recentCommands = m.recent;
            this.renderRecent();
        }
    }

    renderRecent() {
        const list = this.el.recentList;
        if (!this.recentCommands.length) {
            list.innerHTML = '<li class="recent-empty">No commands yet. Say the wake word to begin.</li>';
            return;
        }
        list.innerHTML = '';
        for (const c of this.recentCommands) {
            const li = document.createElement('li');
            const text = document.createElement('span');
            text.className = 'cmd-text';
            text.textContent = `"${c.text}"`;
            const meta = document.createElement('span');
            meta.className = 'cmd-meta';
            meta.dataset.ts = c.ts;
            meta.dataset.duration = c.duration_ms;
            meta.textContent = this.formatRecentMeta(c);
            li.appendChild(text);
            li.appendChild(meta);
            list.appendChild(li);
        }
    }

    formatRecentMeta(c) {
        const ago = this.relTime(c.ts);
        const dur = `${(c.duration_ms / 1000).toFixed(1)}s`;
        return `${ago} · ${dur}`;
    }

    relTime(ts) {
        const seconds = Math.max(0, Math.floor(Date.now() / 1000 - ts));
        if (seconds < 5) return 'just now';
        if (seconds < 60) return `${seconds}s ago`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h ago`;
        return `${Math.floor(hours / 24)}d ago`;
    }

    tickRelative() {
        // Update active utterance duration display.
        if (this.utteranceStart) {
            const s = (Date.now() - this.utteranceStart) / 1000;
            this.el.duration.textContent = `${s.toFixed(1)}s`;
        }
        // Refresh "x ago" labels in the recent list.
        for (const meta of this.el.recentList.querySelectorAll('.cmd-meta')) {
            const ts = parseFloat(meta.dataset.ts);
            const dur = parseFloat(meta.dataset.duration);
            if (!isNaN(ts) && !isNaN(dur)) {
                meta.textContent = `${this.relTime(ts)} · ${(dur / 1000).toFixed(1)}s`;
            }
        }
    }
}

class BluetoothPanel {
    constructor(el) {
        this.el = el;
        this.devices = [];
        this.scanning = false;
        this.busyMacs = new Set();
        this.open = false;
        this.refreshTimer = null;
        this.scanCountdownTimer = null;

        this.el.btToggle.addEventListener('click', () => this.togglePanel());
        this.el.btScan.addEventListener('click', () => this.startScan());
        this.el.btRefresh.addEventListener('click', () => this.refresh());

        // Initial fetch so the badge is accurate even before the panel is opened.
        this.refresh().catch(() => {});
    }

    togglePanel() {
        this.open = !this.open;
        this.el.btPanel.hidden = !this.open;
        this.el.btToggle.setAttribute('aria-expanded', String(this.open));
        if (this.open) {
            this.refresh().catch(() => {});
        }
    }

    setError(msg) {
        if (!msg) {
            this.el.btError.hidden = true;
            this.el.btError.textContent = '';
        } else {
            this.el.btError.hidden = false;
            this.el.btError.textContent = msg;
        }
    }

    async refresh() {
        try {
            const res = await fetch('/api/bluetooth/devices');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.devices = Array.isArray(data.devices) ? data.devices : [];
            this.scanning = !!data.scanning;
            this.setError(null);
            this.render();
        } catch (err) {
            this.setError(`Could not load devices: ${err.message}`);
        }
    }

    async startScan() {
        try {
            this.setError(null);
            this.scanning = true;
            this.renderScanButton(8);
            const res = await fetch('/api/bluetooth/scan', { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            // The backend scans for ~8s. Poll the device list while it runs.
            this.startScanCountdown(8);
            this.startAutoRefresh(2000, 14000);
        } catch (err) {
            this.scanning = false;
            this.renderScanButton();
            this.setError(`Scan failed: ${err.message}`);
        }
    }

    startScanCountdown(seconds) {
        clearInterval(this.scanCountdownTimer);
        let remaining = seconds;
        this.renderScanButton(remaining);
        this.scanCountdownTimer = setInterval(() => {
            remaining -= 1;
            if (remaining <= 0) {
                clearInterval(this.scanCountdownTimer);
                this.scanCountdownTimer = null;
                this.scanning = false;
                this.renderScanButton();
                this.refresh().catch(() => {});
            } else {
                this.renderScanButton(remaining);
            }
        }, 1000);
    }

    startAutoRefresh(intervalMs, totalMs) {
        clearInterval(this.refreshTimer);
        const stopAt = Date.now() + totalMs;
        this.refreshTimer = setInterval(() => {
            if (Date.now() > stopAt) {
                clearInterval(this.refreshTimer);
                this.refreshTimer = null;
                return;
            }
            this.refresh().catch(() => {});
        }, intervalMs);
    }

    async connect(mac) {
        if (this.busyMacs.has(mac)) return;
        this.busyMacs.add(mac);
        this.setError(null);
        this.render();
        try {
            const res = await fetch('/api/bluetooth/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mac }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        } catch (err) {
            this.setError(`Could not connect: ${err.message}`);
        } finally {
            this.busyMacs.delete(mac);
            await this.refresh().catch(() => {});
        }
    }

    async disconnect(mac) {
        if (this.busyMacs.has(mac)) return;
        this.busyMacs.add(mac);
        this.setError(null);
        this.render();
        try {
            const res = await fetch('/api/bluetooth/disconnect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mac }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        } catch (err) {
            this.setError(`Could not disconnect: ${err.message}`);
        } finally {
            this.busyMacs.delete(mac);
            await this.refresh().catch(() => {});
        }
    }

    renderScanButton(secondsLeft) {
        const btn = this.el.btScan;
        if (this.scanning) {
            btn.setAttribute('aria-busy', 'true');
            btn.disabled = true;
            this.el.btScanLabel.textContent = secondsLeft
                ? `Scanning… ${secondsLeft}s`
                : 'Scanning…';
        } else {
            btn.removeAttribute('aria-busy');
            btn.disabled = false;
            this.el.btScanLabel.textContent = 'Scan for devices';
        }
    }

    render() {
        // Header badge: shows count of connected devices.
        const connected = this.devices.filter(d => d.connected);
        if (connected.length > 0) {
            this.el.btBadge.hidden = false;
            this.el.btBadge.textContent = String(connected.length);
            this.el.btSub.textContent = connected.length === 1
                ? `Connected to ${connected[0].name}.`
                : `Connected to ${connected.length} devices.`;
        } else {
            this.el.btBadge.hidden = true;
            this.el.btSub.textContent = 'Pair a speaker or headset to route assistant audio.';
        }

        this.renderScanButton();

        const list = this.el.btList;
        if (!this.devices.length) {
            list.innerHTML = `<li class="bt-empty">${
                this.scanning
                    ? 'Looking for devices… make sure yours is in pairing mode.'
                    : 'No devices yet. Tap “Scan for devices” to discover nearby speakers and headsets.'
            }</li>`;
            return;
        }

        list.innerHTML = '';
        for (const dev of this.devices) {
            list.appendChild(this.buildItem(dev));
        }
    }

    buildItem(dev) {
        const li = document.createElement('li');
        li.className = 'bt-item' + (dev.connected ? ' is-connected' : '');

        const icon = document.createElement('div');
        icon.className = 'bt-icon';
        icon.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7l10 10-5 5V2l5 5L7 17"/></svg>`;

        const info = document.createElement('div');
        info.className = 'bt-info';
        const name = document.createElement('div');
        name.className = 'bt-name';
        name.textContent = dev.name || dev.mac;
        const meta = document.createElement('div');
        meta.className = 'bt-meta';
        const mac = document.createElement('span');
        mac.textContent = dev.mac;
        meta.appendChild(mac);
        if (dev.connected) {
            const tag = document.createElement('span');
            tag.className = 'bt-tag is-connected';
            tag.textContent = 'Connected';
            meta.appendChild(tag);
        } else if (dev.paired) {
            const tag = document.createElement('span');
            tag.className = 'bt-tag is-paired';
            tag.textContent = 'Paired';
            meta.appendChild(tag);
        }
        info.appendChild(name);
        info.appendChild(meta);

        const btn = document.createElement('button');
        btn.type = 'button';
        const busy = this.busyMacs.has(dev.mac);
        if (dev.connected) {
            btn.className = 'btn btn-ghost';
            btn.textContent = busy ? 'Disconnecting…' : 'Disconnect';
            btn.addEventListener('click', () => this.disconnect(dev.mac));
        } else {
            btn.className = 'btn btn-primary';
            btn.textContent = busy ? 'Connecting…' : (dev.paired ? 'Connect' : 'Pair & connect');
            btn.addEventListener('click', () => this.connect(dev.mac));
        }
        if (busy) {
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
        }

        li.appendChild(icon);
        li.appendChild(info);
        li.appendChild(btn);
        return li;
    }
}

class VolumeControl {
    constructor() {
        this.slider = document.getElementById('volume-slider');
        this.value = document.getElementById('volume-value');
        this.pendingPost = null;
        this.postTimer = null;

        this.slider.addEventListener('input', () => this.onInput());
        this.refresh().catch(() => {});
    }

    async refresh() {
        try {
            const res = await fetch('/api/volume');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.apply(data.level);
        } catch (_) {
            this.value.textContent = '—';
        }
    }

    apply(level) {
        const pct = Math.round(Math.max(0, Math.min(1, level)) * 100);
        this.slider.value = String(pct);
        this.value.textContent = `${pct}%`;
    }

    onInput() {
        const pct = parseInt(this.slider.value, 10);
        this.value.textContent = `${pct}%`;
        // Debounce — wpctl is fast but we don't need a call per pixel of drag.
        clearTimeout(this.postTimer);
        this.postTimer = setTimeout(() => this.post(pct / 100), 80);
    }

    async post(level) {
        try {
            const res = await fetch('/api/volume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ level }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            // Only resync the slider if the user isn't actively dragging right now.
            if (document.activeElement !== this.slider) {
                this.apply(data.level);
            }
        } catch (_) {
            // Leave the slider where the user put it; refresh on next page load.
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
});

