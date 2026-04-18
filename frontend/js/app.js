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
            particles: document.getElementById('particles'),
        };

        this.init();
    }

    init() {
        this.createParticles();
        this.connectWebSocket();
        this.startClock();
        this.fetchWeather();

        // Refresh weather every 10 minutes
        setInterval(() => this.fetchWeather(), 10 * 60 * 1000);
    }

    // ===== Particles =====
    createParticles() {
        const count = 30;
        for (let i = 0; i < count; i++) {
            const particle = document.createElement('div');
            particle.className = 'particle';
            particle.style.left = `${Math.random() * 100}%`;
            particle.style.animationDelay = `${Math.random() * 20}s`;
            particle.style.animationDuration = `${15 + Math.random() * 15}s`;
            this.elements.particles.appendChild(particle);
        }
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
            case 'state':
                this.updateState(message.state);
                break;
            case 'weather':
                this.updateWeather(message.data);
                break;
            case 'transcript':
                this.showTranscript(message.text, message.label);
                break;
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
        }
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

        // Time
        const hours = now.getHours().toString().padStart(2, '0');
        const minutes = now.getMinutes().toString().padStart(2, '0');
        this.elements.time.textContent = `${hours}:${minutes}`;

        // Date
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

        // Update weather icon based on condition
        const iconMap = {
            '01d': '☀️', '01n': '🌙',
            '02d': '⛅', '02n': '☁️',
            '03d': '☁️', '03n': '☁️',
            '04d': '☁️', '04n': '☁️',
            '09d': '🌧️', '09n': '🌧️',
            '10d': '🌦️', '10n': '🌧️',
            '11d': '⛈️', '11n': '⛈️',
            '13d': '❄️', '13n': '❄️',
            '50d': '🌫️', '50n': '🌫️',
        };
        this.elements.weatherIcon.textContent = iconMap[data.icon] || '🌡️';
    }
}

// Start app
document.addEventListener('DOMContentLoaded', () => {
    window.assistant = new PiAssistant();
});
