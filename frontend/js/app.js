/**
 * Pi Assistant Frontend
 * Handles WebSocket connection, time/weather updates, and state animations
 */

class PiAssistant {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.currentState = 'idle';

        // DOM elements
        this.elements = {
            time: document.getElementById('time'),
            date: document.getElementById('date'),
            temp: document.getElementById('temp'),
            weatherDesc: document.getElementById('weather-desc'),
            weatherIcon: document.getElementById('weather-icon'),
            orb: document.getElementById('orb'),
            status: document.getElementById('status'),
            transcript: document.getElementById('transcript'),
            transcriptContent: document.getElementById('transcript-content'),
            idleGifStage: document.getElementById('idle-gif-stage'),
            idleGif: document.getElementById('idle-gif'),
            nowPlaying: document.getElementById('now-playing'),
            npArt: document.getElementById('np-art'),
            npTitle: document.getElementById('np-title'),
            npChannel: document.getElementById('np-channel'),
        };
        // stars/particles removed — design now uses a solid bg + waveform.

        // Idle-GIF rotation
        this.idleGifs = [];
        this.idleGifStartTimer = null;   // fires once to begin rotation
        this.idleGifRotateTimer = null;  // interval rotating the image
        this.idleGifStartDelayMs = 15000;
        this.idleGifRotateMs = 12000;
        this.lastIdleGif = null;

        this.init();
    }

    init() {
        this.loadIdleGifs();
        this.connectWebSocket();
        this.startClock();
        this.fetchWeather();

        // Refresh weather every 10 minutes
        setInterval(() => this.fetchWeather(), 10 * 60 * 1000);
    }

    // ===== WebSocket =====
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
        };

        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleMessage(message);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.scheduleReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            this.reconnectAttempts++;
            console.log(`Reconnecting in ${delay}ms...`);
            setTimeout(() => this.connectWebSocket(), delay);
        }
    }

    handleMessage(message) {
        switch (message.type) {
            case 'server_id':
                this.handleServerId(message.id);
                break;
            case 'state':
                this.updateState(message.state);
                break;
            case 'weather':
                this.updateWeather(message.data);
                break;
            case 'transcript':
                this.showTranscript(message.text, message.label);
                break;
            case 'music':
                this.updateNowPlaying(message.track);
                break;
        }
    }

    updateNowPlaying(track) {
        const card = this.elements.nowPlaying;
        if (!card) return;
        if (!track || !track.title) {
            card.classList.remove('visible');
            card.setAttribute('aria-hidden', 'true');
            return;
        }
        this.elements.npTitle.textContent = track.title;
        const meta = [track.channel, track.duration].filter(Boolean).join(' · ');
        this.elements.npChannel.textContent = meta;

        const art = this.elements.npArt;
        if (track.thumbnail) {
            art.innerHTML = `<img alt="" referrerpolicy="no-referrer" src="${track.thumbnail}">`;
        } else {
            art.innerHTML =
                `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">` +
                `<path d="M9 18V5l12-2v13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>` +
                `<circle cx="6" cy="18" r="3" fill="currentColor"/>` +
                `<circle cx="18" cy="16" r="3" fill="currentColor"/></svg>`;
        }
        card.classList.add('visible');
        card.setAttribute('aria-hidden', 'false');
    }

    handleServerId(id) {
        if (!id) return;
        // First sighting after page load: remember it.
        if (this.serverId === undefined) {
            this.serverId = id;
            return;
        }
        // Backend restarted with new assets — force a fresh page load.
        if (id !== this.serverId) {
            window.location.reload();
        }
    }

    // ===== State Management =====
    updateState(state) {
        const { orb, status } = this.elements;
        this.currentState = state;

        // Remove all state classes
        orb.classList.remove('idle', 'listening', 'thinking', 'speaking');

        // Add current state
        orb.classList.add(state);

        // Update status text with animation
        const statusText = {
            idle: 'Ready',
            listening: 'Listening',
            thinking: 'Processing',
            speaking: 'Speaking',
        };

        status.textContent = statusText[state] || state;
        status.classList.toggle('active', state !== 'idle');

        // Hide transcript when going back to idle
        if (state === 'idle') {
            setTimeout(() => this.hideTranscript(), 2000);
            this.scheduleIdleGif();
        } else {
            this.cancelIdleGif();
        }
    }

    // ===== Idle GIFs =====
    async loadIdleGifs() {
        try {
            const response = await fetch('/static/gifs/index.json', { cache: 'no-store' });
            if (!response.ok) return;
            const list = await response.json();
            if (Array.isArray(list)) {
                this.idleGifs = list.filter((n) => typeof n === 'string' && n.endsWith('.gif'));
            }
        } catch (error) {
            console.warn('No idle GIFs loaded:', error);
        }
        // If we were already idle when the list finished loading, kick off rotation now.
        if (this.currentState === 'idle' && this.idleGifs.length && !this.idleGifStartTimer && !this.idleGifRotateTimer) {
            this.scheduleIdleGif();
        }
    }

    scheduleIdleGif() {
        this.cancelIdleGif();
        if (!this.idleGifs.length) return;
        this.idleGifStartTimer = setTimeout(() => {
            this.showNextIdleGif();
            this.idleGifRotateTimer = setInterval(
                () => this.showNextIdleGif(),
                this.idleGifRotateMs,
            );
        }, this.idleGifStartDelayMs);
    }

    cancelIdleGif() {
        if (this.idleGifStartTimer) {
            clearTimeout(this.idleGifStartTimer);
            this.idleGifStartTimer = null;
        }
        if (this.idleGifRotateTimer) {
            clearInterval(this.idleGifRotateTimer);
            this.idleGifRotateTimer = null;
        }
        document.body.classList.remove('show-idle-gif');
    }

    showNextIdleGif() {
        if (!this.idleGifs.length) return;
        let pick;
        if (this.idleGifs.length === 1) {
            pick = this.idleGifs[0];
        } else {
            do {
                pick = this.idleGifs[Math.floor(Math.random() * this.idleGifs.length)];
            } while (pick === this.lastIdleGif);
        }
        this.lastIdleGif = pick;
        this.elements.idleGif.src = `/static/gifs/${encodeURIComponent(pick)}`;
        document.body.classList.add('show-idle-gif');
    }

    // ===== Transcript =====
    showTranscript(text, label = 'You said') {
        const { transcript, transcriptContent } = this.elements;
        const labelEl = transcript.querySelector('.label');

        labelEl.textContent = label;
        transcriptContent.textContent = text;
        transcript.classList.add('visible');
    }

    hideTranscript() {
        this.elements.transcript.classList.remove('visible');
    }

    // ===== Clock =====
    startClock() {
        this.updateClock();
        setInterval(() => this.updateClock(), 1000);
    }

    updateClock() {
        const now = new Date();

        let hours24 = now.getHours();
        const ampm = hours24 >= 12 ? 'PM' : 'AM';
        let hours = hours24 % 12;
        if (hours === 0) hours = 12;
        const minutes = now.getMinutes().toString().padStart(2, '0');
        this.elements.time.innerHTML = `${hours}<span class="colon">:</span>${minutes}<span class="ampm">${ampm}</span>`;

        const options = { weekday: 'long', month: 'long', day: 'numeric' };
        this.elements.date.textContent = now.toLocaleDateString('en-US', options);
    }

    // ===== Weather =====
    async fetchWeather() {
        try {
            const response = await fetch('/api/weather');
            const data = await response.json();
            this.updateWeather(data);
        } catch (error) {
            console.error('Failed to fetch weather:', error);
        }
    }

    updateWeather(data) {
        if (data.error) {
            this.elements.temp.textContent = '--°';
            this.elements.weatherDesc.textContent = 'Unavailable';
            return;
        }

        this.elements.temp.textContent = `${data.temp_c}°C / ${data.temp_f}°F`;
        this.elements.weatherDesc.textContent = data.description;
        this.elements.weatherIcon.innerHTML = this.weatherSvg(data.icon);
    }

    weatherSvg(code) {
        const sun = `<circle cx="32" cy="32" r="12" fill="#fbbf24"/>` +
            `<g stroke="#fbbf24" stroke-width="3" stroke-linecap="round">` +
            `<line x1="32" y1="6"  x2="32" y2="14"/>` +
            `<line x1="32" y1="50" x2="32" y2="58"/>` +
            `<line x1="6"  y1="32" x2="14" y2="32"/>` +
            `<line x1="50" y1="32" x2="58" y2="32"/>` +
            `<line x1="13" y1="13" x2="19" y2="19"/>` +
            `<line x1="45" y1="45" x2="51" y2="51"/>` +
            `<line x1="51" y1="13" x2="45" y2="19"/>` +
            `<line x1="19" y1="45" x2="13" y2="51"/></g>`;
        const moon = `<path d="M42 36a18 18 0 1 1-14-28 14 14 0 0 0 14 28z" fill="#e5e7eb"/>`;
        const cloud = (fill = '#cbd5e1') =>
            `<path d="M20 44h26a10 10 0 0 0 0-20 12 12 0 0 0-22-4 9 9 0 0 0-4 24z" fill="${fill}"/>`;
        const sunCloud = `<g transform="translate(-6,-6)">${sun}</g>` + cloud('#e2e8f0');
        const rain = cloud('#94a3b8') +
            `<g stroke="#38bdf8" stroke-width="3" stroke-linecap="round">` +
            `<line x1="22" y1="48" x2="19" y2="56"/>` +
            `<line x1="32" y1="48" x2="29" y2="56"/>` +
            `<line x1="42" y1="48" x2="39" y2="56"/></g>`;
        const storm = cloud('#64748b') +
            `<path d="M30 46l-6 10h6l-4 8 12-12h-6l4-6z" fill="#facc15"/>`;
        const snow = cloud('#e2e8f0') +
            `<g fill="#f0f9ff">` +
            `<circle cx="22" cy="52" r="2.5"/>` +
            `<circle cx="32" cy="56" r="2.5"/>` +
            `<circle cx="42" cy="52" r="2.5"/></g>`;
        const mist = `<g stroke="#cbd5e1" stroke-width="4" stroke-linecap="round">` +
            `<line x1="10" y1="22" x2="54" y2="22"/>` +
            `<line x1="14" y1="32" x2="50" y2="32"/>` +
            `<line x1="10" y1="42" x2="54" y2="42"/></g>`;

        const map = {
            '01d': sun,          '01n': moon,
            '02d': sunCloud,     '02n': cloud('#cbd5e1'),
            '03d': cloud(),      '03n': cloud(),
            '04d': cloud('#94a3b8'), '04n': cloud('#94a3b8'),
            '09d': rain,         '09n': rain,
            '10d': rain,         '10n': rain,
            '11d': storm,        '11n': storm,
            '13d': snow,         '13n': snow,
            '50d': mist,         '50n': mist,
        };
        const body = map[code] || sun;
        return `<svg viewBox="0 0 64 64" width="1em" height="1em" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
    }
}

// Start app
document.addEventListener('DOMContentLoaded', () => {
    window.assistant = new PiAssistant();
});
