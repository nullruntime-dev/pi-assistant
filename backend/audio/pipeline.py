import asyncio
import queue
from typing import TYPE_CHECKING, Any

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    from backend.main import AssistantState
    from backend.config import Settings


class AudioPipeline:
    """
    Main audio pipeline:
    1. Listen for wake word
    2. Record user speech
    3. Transcribe to text
    4. Send to agent
    5. Speak response
    """

    def __init__(self, assistant: "AssistantState", settings: "Settings"):
        self.assistant = assistant
        self.settings = settings
        self.running = False

        # Audio queue for mic input
        self.audio_queue: queue.Queue = queue.Queue()

        # Components (lazy init to defer imports)
        self._wake_word: Any = None
        self._stt: Any = None
        self._tts: Any = None
        self._agent: Any = None

    @property
    def wake_word(self):
        if self._wake_word is None:
            from backend.audio.wake_word import WakeWordDetector
            self._wake_word = WakeWordDetector(self.settings.wake_word)
        return self._wake_word

    @property
    def stt(self):
        if self._stt is None:
            from backend.audio.stt import SpeechToText
            self._stt = SpeechToText(model_size="base")
        return self._stt

    @property
    def tts(self):
        if self._tts is None:
            from backend.audio.tts import TextToSpeech
            self._tts = TextToSpeech()
        return self._tts

    @property
    def agent(self):
        if self._agent is None:
            from backend.agent.assistant import Assistant
            self._agent = Assistant(self.settings.google_api_key)
        return self._agent

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for audio stream - runs in separate thread."""
        if status:
            print(f"Audio status: {status}")
        self.audio_queue.put(indata.copy())

    async def run(self):
        """Main loop - listen for wake word and process commands."""
        self.running = True

        # Start audio stream
        stream = sd.InputStream(
            samplerate=self.settings.sample_rate,
            channels=self.settings.channels,
            dtype=np.float32,
            blocksize=1024,
            callback=self._audio_callback,
        )

        with stream:
            print("Audio pipeline started. Listening for wake word...")

            while self.running:
                try:
                    # Get audio chunk - run blocking call in thread
                    try:
                        audio_chunk = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: self.audio_queue.get(timeout=0.1)
                        )
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                        continue

                    # Check for wake word
                    if self.wake_word.detect(audio_chunk):
                        await self._handle_activation()

                except Exception as e:
                    print(f"Pipeline error: {e}")
                    await asyncio.sleep(0.1)

    async def _handle_activation(self):
        """Handle wake word detection - record, transcribe, respond."""
        print("Wake word detected!")
        self.wake_word.reset()

        try:
            # Update state to listening
            await self.assistant.set_state("listening")

            # Record audio until silence
            audio_buffer = []
            silence_chunks = 0
            max_silence = 15  # ~1.5 seconds of silence
            max_duration = 100  # ~10 seconds max

            for _ in range(max_duration):
                try:
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.audio_queue.get(timeout=0.1)
                    )
                    audio_buffer.append(chunk)

                    # Simple silence detection (RMS energy)
                    rms = np.sqrt(np.mean(chunk**2))
                    if rms < 0.01:
                        silence_chunks += 1
                    else:
                        silence_chunks = 0

                    if silence_chunks >= max_silence:
                        break

                except queue.Empty:
                    await asyncio.sleep(0.01)

            if not audio_buffer:
                print("No audio captured")
                await self.assistant.set_state("idle")
                return

            # Combine audio
            audio = np.concatenate(audio_buffer).flatten()

            # Transcribe
            await self.assistant.set_state("thinking")
            try:
                text = await asyncio.to_thread(
                    self.stt.transcribe, audio, self.settings.sample_rate
                )
                print(f"User said: {text}")
                await self.assistant.send_transcript(text, "You said")
            except Exception as e:
                print(f"STT error: {e}")
                await self._speak_error("Sorry, I couldn't understand that.")
                return

            if not text.strip():
                await self.assistant.set_state("idle")
                return

            # Get response from agent
            try:
                response = await self.agent.process(text)
                print(f"Assistant: {response}")
                await self.assistant.send_transcript(response, "Assistant")
            except Exception as e:
                print(f"Agent error: {e}")
                await self._speak_error("Sorry, I'm having trouble thinking right now.")
                return

            # Speak response
            await self.assistant.set_state("speaking")
            try:
                await asyncio.to_thread(self.tts.speak, response)
            except Exception as e:
                print(f"TTS error: {e}")

        except Exception as e:
            print(f"Activation error: {e}")
        finally:
            # Always return to idle
            await self.assistant.set_state("idle")

    async def _speak_error(self, message: str):
        """Speak an error message."""
        try:
            await self.assistant.set_state("speaking")
            await asyncio.to_thread(self.tts.speak, message)
        except Exception:
            pass
        finally:
            await self.assistant.set_state("idle")

    async def stop(self):
        """Stop the pipeline."""
        self.running = False
