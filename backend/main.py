import asyncio
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_settings
from backend.services.weather import WeatherService

# Audio pipeline - optional, requires numpy/sounddevice
try:
    from backend.audio.pipeline import AudioPipeline
    AUDIO_AVAILABLE = True
except ImportError as e:
    print(f"Audio pipeline unavailable: {e}")
    print("UI will work, but voice features disabled. Install: pip install numpy sounddevice openwakeword faster-whisper")
    AUDIO_AVAILABLE = False
    AudioPipeline = None


class AssistantState:
    """Tracks assistant state and connected clients."""

    def __init__(self):
        self.clients: list[WebSocket] = []
        self.state = "idle"  # idle, listening, thinking, speaking

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        for client in self.clients:
            try:
                await client.send_json(message)
            except Exception:
                pass

    async def set_state(self, new_state: str):
        """Update state and notify clients."""
        self.state = new_state
        await self.broadcast({"type": "state", "state": new_state})

    async def send_transcript(self, text: str, label: str = "You said"):
        """Send transcript to UI."""
        await self.broadcast({"type": "transcript", "text": text, "label": label})


assistant = AssistantState()
weather_service = WeatherService()
audio_pipeline = None  # AudioPipeline instance, set in lifespan if available


@asynccontextmanager
async def lifespan(app: FastAPI):
    global audio_pipeline

    # Startup
    settings = get_settings()

    if AUDIO_AVAILABLE:
        audio_pipeline = AudioPipeline(
            assistant=assistant,
            settings=settings,
        )
        # Start audio pipeline in background
        asyncio.create_task(audio_pipeline.run())
    else:
        print("Running in UI-only mode (no audio)")

    yield

    # Shutdown
    if audio_pipeline:
        await audio_pipeline.stop()


app = FastAPI(title="Pi Assistant", lifespan=lifespan)

# Serve frontend
frontend_path = Path(__file__).resolve().parent.parent / "frontend"
print(f"Frontend path: {frontend_path}")
app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


@app.get("/")
async def index():
    return FileResponse(frontend_path / "index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    assistant.clients.append(websocket)

    # Send current state
    await websocket.send_json({"type": "state", "state": assistant.state})

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle client messages
            if message.get("type") == "get_weather":
                weather = await weather_service.get_current()
                await websocket.send_json({"type": "weather", "data": weather})

    except WebSocketDisconnect:
        assistant.clients.remove(websocket)


@app.get("/api/weather")
async def get_weather():
    return await weather_service.get_current()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
