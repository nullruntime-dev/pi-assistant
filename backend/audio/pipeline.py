import asyncio
import collections
import queue
import re
import time
from typing import TYPE_CHECKING, Any

import numpy as np
import sounddevice as sd


# Said by the user to abort the current turn — no LLM call, no follow-up,
# kill any playing music, and drop straight back to wake-word mode. Matched
# against the WHOLE transcript (lowercased, stripped of trailing punctuation),
# capped at ~5 words so longer LLM-worthy queries that happen to contain
# "stop" still fall through (e.g. "play Stop by the Spice Girls").
_DISMISS_RE = re.compile(
    r"^(?:"
    r"stop\b.*"                                   # stop / stop it / stop the music / stop talking
    r"|(?:quit|exit|cancel|enough)\b.*"           # quit / cancel that / enough already
    r"|(?:never\s*mind|forget\s+it)\b.*"
    r"|shut\s+up\b.*|be\s+quiet\b.*"
    r"|(?:leave\s+me\s+alone|go\s+away)\b.*"
    r"|fuck\s+(?:off|you)\b.*|piss\s+off\b.*"
    r")$",
    re.IGNORECASE,
)


def _is_dismiss(text: str) -> bool:
    if not text:
        return False
    cleaned = text.strip().rstrip(".!?,").strip().lower()
    if not cleaned or len(cleaned.split()) > 5:
        return False
    return bool(_DISMISS_RE.match(cleaned))

if TYPE_CHECKING:
    from backend.main import AssistantState
    from backend.config import Settings


class AudioPipeline:
    """
    Main audio pipeline:
    1. Listen for wake word
    2. Record user speech
    3. Transcribe to text
    4. Stream agent response -> speak sentence by sentence
    """

    def __init__(self, assistant: "AssistantState", settings: "Settings", metrics: Any = None):
        self.assistant = assistant
        self.settings = settings
        self.metrics = metrics
        self.running = False

        self.audio_queue: queue.Queue = queue.Queue()

        # Rolling RMS samples used to estimate the ambient noise floor so the
        # silence threshold can adapt to a room with a TV vs a quiet room.
        # ~200 chunks * 64ms = ~12.8s of recent audio; the lower-percentile is
        # the floor (loud bursts don't poison it).
        self._ambient_rms: collections.deque[float] = collections.deque(maxlen=200)

        self._wake_word: Any = None
        self._stt: Any = None
        self._tts: Any = None
        self._agent: Any = None

    @property
    def wake_word(self):
        if self._wake_word is None:
            from backend.audio.wake_word import WakeWordDetector
            self._wake_word = WakeWordDetector(
                self.settings.wake_word,
                threshold=self.settings.wake_word_threshold,
                consecutive_frames=self.settings.wake_word_consecutive_frames,
            )
        return self._wake_word

    @property
    def stt(self):
        if self._stt is None:
            from backend.audio.stt import SpeechToText
            self._stt = SpeechToText(model_size=self.settings.stt_model_size)
        return self._stt

    @property
    def tts(self):
        if self._tts is None:
            from backend.audio.tts import TextToSpeech
            self._tts = TextToSpeech(
                voice=self.settings.tts_voice,
                length_scale=self.settings.tts_length_scale,
            )
        return self._tts

    @property
    def agent(self):
        if self._agent is None:
            from backend.agent.assistant import Assistant
            self._agent = Assistant(
                self.settings.google_api_key,
                model_name=self.settings.llm_model,
            )
        return self._agent

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"Audio status: {status}")
        self.audio_queue.put(indata.copy())
        try:
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            self._ambient_rms.append(rms)
            if self.metrics is not None:
                self.metrics.push_mic_rms(rms)
        except Exception:
            pass

    def _ambient_floor(self) -> float:
        """Lower-quartile RMS over the recent rolling window — robust to bursts
        of speech, so it tracks the actual room floor (TV included)."""
        if len(self._ambient_rms) < 30:
            return 0.006
        samples = sorted(self._ambient_rms)
        return samples[len(samples) // 4]

    def _warmup(self):
        """Pre-load heavy models so the first activation isn't slow."""
        try:
            self.tts.warmup()
        except Exception as e:
            print(f"TTS warmup failed: {e}")

    async def run(self):
        """Main loop - listen for wake word and process commands."""
        self.running = True

        # Touch wake word to trigger init before the stream opens
        _ = self.wake_word
        # Pre-load TTS in background so first response isn't delayed
        asyncio.get_event_loop().run_in_executor(None, self._warmup)

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
                    try:
                        audio_chunk = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: self.audio_queue.get(timeout=0.1)
                        )
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                        continue

                    if self.wake_word.detect(audio_chunk):
                        if self.metrics is not None:
                            await self.metrics.on_wake(self.wake_word.last_score)
                        await self._handle_activation()

                except Exception as e:
                    print(f"Pipeline error: {e}")
                    await asyncio.sleep(0.1)

    async def _handle_activation(self):
        """Handle wake word detection - record, transcribe, respond, then follow up."""
        from backend.services.music import music_player

        # Duck any currently-playing music so the mic can hear the user clearly.
        had_music_before = music_player.is_playing()
        if had_music_before:
            music_player.duck()

        self.wake_word.reset()
        self._drain_queue()

        try:
            is_follow_up = False
            prev_user_text: str | None = None
            while self.running:
                text = await self._listen_and_transcribe(is_follow_up)
                if text is None:
                    break

                # User dismissed the assistant — kill music, skip the LLM,
                # and exit the session. Works in both initial and follow-up
                # turns.
                if _is_dismiss(text):
                    print(f"[dismiss] ending session: {text!r}")
                    if music_player.is_playing():
                        music_player.stop()
                    had_music_before = False  # don't unduck a stopped track
                    break

                # In follow-up mode, gate on whether the transcript is plausibly
                # addressed to the assistant — keeps TV/background speech from
                # hijacking the session.
                if is_follow_up and prev_user_text is not None:
                    relevant = await self.agent.is_follow_up_relevant(prev_user_text, text)
                    if not relevant:
                        print(f"[follow-up] dropped unrelated utterance: {text!r}")
                        break

                await self._stream_respond(text)
                prev_user_text = text

                # If the response started NEW music, end follow-up (mic would be flooded).
                # Music that was already playing before activation is still ducked, so it's fine.
                if music_player.is_playing() and not had_music_before:
                    break

                is_follow_up = True
                # Let any TTS tail clear the audio device before re-listening.
                await asyncio.sleep(0.25)

        except Exception as e:
            print(f"Activation error: {e}")
        finally:
            if self._agent is not None:
                self._agent.reset_conversation()
            # Restore any music we ducked at the start (no-op if it was stopped).
            music_player.unduck()
            await self.assistant.set_state("idle")

    async def _listen_and_transcribe(self, is_follow_up: bool):
        """Record one utterance and transcribe it. Returns None if no speech."""
        await self.assistant.set_state("listening")
        if self.metrics is not None:
            await self.metrics.on_listen_start()
        self._drain_queue()

        # 1024-sample chunks at 16 kHz → ~0.064s/chunk.
        audio_buffer = []
        silence_chunks = 0
        voiced_chunks = 0
        max_silence = 14        # ~0.9s of trailing silence -> end of utterance
        max_duration = 235      # ~15s safety cap (don't hit on normal speech)
        min_voiced = 3          # require at least a bit of actual speech
        # Adapt the speech/silence threshold to the current room floor (TV,
        # fan, AC) so distant background speech doesn't keep the recorder
        # open forever. Floor × 3 keeps close-mic speech well above ambient
        # while a hard min handles a dead-quiet room.
        silence_rms = max(0.018, self._ambient_floor() * 3.0)
        print(f"[vad] ambient_floor={self._ambient_floor():.4f} silence_rms={silence_rms:.4f}")
        # Follow-up mode: if no speech starts within ~6s, drop back to wake word.
        wait_for_speech_budget = 95 if is_follow_up else max_duration
        pre_speech_silence = 0

        for _ in range(max_duration):
            try:
                chunk = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.audio_queue.get(timeout=0.1)
                )

                rms = float(np.sqrt(np.mean(chunk**2)))
                voiced = rms >= silence_rms

                if is_follow_up and voiced_chunks == 0 and not voiced:
                    pre_speech_silence += 1
                    if pre_speech_silence >= wait_for_speech_budget:
                        return None
                    continue

                audio_buffer.append(chunk)
                if voiced:
                    voiced_chunks += 1
                    silence_chunks = 0
                else:
                    silence_chunks += 1

                if voiced_chunks >= min_voiced and silence_chunks >= max_silence:
                    break

            except queue.Empty:
                await asyncio.sleep(0.01)

        if voiced_chunks < min_voiced:
            if not is_follow_up:
                print("No speech captured")
            return None

        audio = np.concatenate(audio_buffer).flatten()

        await self.assistant.set_state("thinking")
        try:
            t_stt = time.monotonic()
            text = await asyncio.to_thread(
                self.stt.transcribe, audio, self.settings.sample_rate
            )
            print(f"[timing] STT {time.monotonic() - t_stt:.2f}s -> {text!r}")
            await self.assistant.send_transcript(text, "You said")
            if self.metrics is not None and text and text.strip():
                await self.metrics.on_transcript_done(text.strip(), t_stt)
        except Exception as e:
            print(f"STT error: {e}")
            await self._speak_error("Sorry, I couldn't understand that.")
            return None

        if not text.strip():
            return None
        return text

    async def _stream_respond(self, user_text: str):
        """Stream agent response and speak sentence by sentence."""
        full_response: list[str] = []
        spoken_any = False
        t_agent = time.monotonic()
        if self.metrics is not None:
            await self.metrics.on_agent_start()

        # TTS playback queue — synthesize happens in a thread, keeps main loop free
        tts_queue: asyncio.Queue = asyncio.Queue()
        speaker_task = asyncio.create_task(self._speaker_worker(tts_queue))

        try:
            async for sentence in self.agent.process_stream(user_text):
                if not sentence.strip():
                    continue
                if not full_response:
                    print(f"[timing] agent first sentence {time.monotonic() - t_agent:.2f}s")
                    if self.metrics is not None:
                        await self.metrics.on_intent_first_token()
                full_response.append(sentence)

                if not spoken_any:
                    spoken_any = True
                    await self.assistant.set_state("speaking")

                await tts_queue.put(sentence)

            # Signal end of stream
            await tts_queue.put(None)
            await speaker_task

        except Exception as e:
            print(f"Stream response error: {e}")
            await tts_queue.put(None)
            try:
                await speaker_task
            except Exception:
                pass
            await self._speak_error("Sorry, I'm having trouble responding right now.")
            return

        if full_response:
            joined = " ".join(full_response)
            await self.assistant.send_transcript(joined, "Assistant")
            print(f"Assistant: {joined}")

        if self.metrics is not None:
            await self.metrics.on_utterance_complete()

    async def _speaker_worker(self, q: asyncio.Queue):
        """Pull sentences off the queue and speak them in order."""
        first = True
        while True:
            sentence = await q.get()
            if sentence is None:
                return
            try:
                if first and self.metrics is not None:
                    await self.metrics.on_tts_first_audio()
                    first = False
                await asyncio.to_thread(self.tts.speak, sentence)
            except Exception as e:
                print(f"TTS error: {e}")

    def _drain_queue(self):
        """Clear buffered audio before recording the user's utterance."""
        try:
            while True:
                self.audio_queue.get_nowait()
        except queue.Empty:
            pass

    async def _speak_error(self, message: str):
        try:
            await self.assistant.set_state("speaking")
            await asyncio.to_thread(self.tts.speak, message)
        except Exception:
            pass
        finally:
            await self.assistant.set_state("idle")

    async def stop(self):
        self.running = False

