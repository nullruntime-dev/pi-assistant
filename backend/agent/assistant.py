import re
import time
from datetime import datetime
from typing import AsyncIterator

from google import genai
from google.genai import types

from backend.services.music import music_player
from backend.services.weather import WeatherService


weather_service = WeatherService()

_SENTENCE_END = re.compile(r'([^.!?\n]+[.!?\n]+)')
_STOP_WORDS = ("stop", "pause", "quiet", "silence", "shut up", "stop music", "stop playing")
_CHAT_IDLE_RESET_SECONDS = 120.0


class Assistant:
    """
    AI Assistant using Google Gemini (google-genai SDK).
    Handles user queries with music playback.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash-lite"):
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self._config = types.GenerateContentConfig(
            system_instruction=self._get_system_instruction(),
            temperature=0.7,
            max_output_tokens=256,
        )
        self._chat = None
        self._last_turn_at: float = 0.0

    def reset_conversation(self):
        """Drop chat history so the next turn starts fresh."""
        self._chat = None
        self._last_turn_at = 0.0

    def _ensure_chat(self):
        """Return a live async chat session, recycling if idle too long."""
        now = time.monotonic()
        if self._chat is None or (now - self._last_turn_at) > _CHAT_IDLE_RESET_SECONDS:
            self._chat = self.client.aio.chats.create(
                model=self.model_name,
                config=self._config,
            )
        self._last_turn_at = now
        return self._chat

    async def is_follow_up_relevant(self, prev_user: str, new_text: str) -> bool:
        """
        Classify whether a follow-up transcript is plausibly addressed to the
        assistant, vs. overheard speech (TV, background conversation).
        Returns True on any error — we'd rather occasionally process junk than
        drop a real follow-up.
        """
        new_stripped = new_text.strip()
        if not new_stripped:
            return False
        # Very short acknowledgements ("thanks", "ok", "yes") are almost always addressed.
        if len(new_stripped.split()) <= 2:
            return True

        prompt = (
            "You gate a voice assistant's follow-up mode. Given the previous user "
            "command and a newly transcribed utterance, decide if the new utterance "
            "is plausibly addressed to the assistant (a follow-up question, a new "
            "command, or an acknowledgement) versus overheard speech like TV, "
            "movie dialogue, or a background conversation.\n"
            "Respond with exactly one word: YES or NO.\n\n"
            f"Previous user command: {prev_user!r}\n"
            f"New utterance: {new_stripped!r}\n"
            "Answer:"
        )
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=4,
                ),
            )
            answer = (getattr(response, "text", "") or "").strip().upper()
            return not answer.startswith("NO")
        except Exception as e:
            print(f"Follow-up relevance check failed: {e}")
            return True

    def _get_system_instruction(self) -> str:
        return """You are a helpful voice assistant running on a Raspberry Pi.
Keep responses concise and conversational - they will be spoken aloud.
Aim for 1-3 short sentences unless the user asks for detail.
Be friendly and natural, like a helpful friend. Use contractions.
Avoid markdown formatting, bullet points, or lists.

IMPORTANT: For music/song requests, respond ONLY with this exact format:
[PLAY_MUSIC: song name or search query]

Examples:
- User: "Play Bohemian Rhapsody" -> [PLAY_MUSIC: Bohemian Rhapsody Queen]
- User: "Play some jazz" -> [PLAY_MUSIC: jazz music relaxing]
- User: "I want to hear Shape of You" -> [PLAY_MUSIC: Shape of You Ed Sheeran]
- User: "Play lo-fi" -> [PLAY_MUSIC: lofi hip hop beats]

For stopping music:
- User: "Stop the music" -> [STOP_MUSIC]
- User: "Pause" -> [STOP_MUSIC]

For time/date requests, respond ONLY with this exact format:
[GET_DATETIME]

Examples:
- User: "What time is it?" -> [GET_DATETIME]
- User: "What's today's date?" -> [GET_DATETIME]
- User: "What day is it?" -> [GET_DATETIME]

For weather requests, respond ONLY with this exact format:
[GET_WEATHER]

Examples:
- User: "What's the weather?" -> [GET_WEATHER]
- User: "How hot is it outside?" -> [GET_WEATHER]
- User: "Is it raining?" -> [GET_WEATHER]

For all other queries, respond normally."""

    async def process_stream(self, user_input: str) -> AsyncIterator[str]:
        """
        Yield response text in speakable chunks (sentences) as they're generated.
        Caller should concatenate all yields to get the full response for UI display.
        """
        # Direct stop-word shortcut (no LLM round trip)
        lower = user_input.lower()
        if any(w in lower for w in _STOP_WORDS) and music_player.is_playing():
            music_player.stop()
            yield "Music stopped."
            return

        buffer = ""
        accumulated = ""
        is_command = None  # None=unknown, True=command tag, False=normal speech

        try:
            chat = self._ensure_chat()
            response = await chat.send_message_stream(user_input)

            async for chunk in response:
                text = getattr(chunk, "text", None)
                if not text:
                    continue
                accumulated += text

                if is_command is None:
                    stripped = accumulated.lstrip()
                    if stripped:
                        is_command = stripped.startswith("[")
                        if not is_command:
                            buffer = accumulated
                elif is_command is False:
                    buffer += text

                if is_command is False:
                    for sentence in self._drain_sentences(buffer):
                        yield sentence
                    buffer = self._tail_after_sentences(buffer)

            if is_command:
                yield await self._resolve_command(accumulated)
                return

            tail = buffer.strip()
            if tail:
                yield tail

        except Exception as e:
            print(f"Agent error: {e}")
            yield "Sorry, I hit a snag thinking about that."

    def _drain_sentences(self, text: str) -> list[str]:
        """Pull complete sentences off the front of the buffer."""
        sentences = []
        for match in _SENTENCE_END.finditer(text):
            s = match.group(1).strip()
            if s:
                sentences.append(s)
        return sentences

    def _tail_after_sentences(self, text: str) -> str:
        """Return whatever's left after the last complete sentence."""
        last_end = 0
        for match in _SENTENCE_END.finditer(text):
            last_end = match.end()
        return text[last_end:]

    async def _resolve_command(self, response_text: str) -> str:
        """Handle a command tag and return the spoken response."""
        m = re.search(r'\[PLAY_MUSIC:\s*(.+?)\]', response_text)
        if m:
            return await music_player.play(m.group(1).strip())

        if re.search(r'\[STOP_MUSIC\]', response_text):
            return music_player.stop()

        if re.search(r'\[GET_DATETIME\]', response_text):
            return self._format_datetime()

        if re.search(r'\[GET_WEATHER\]', response_text):
            return await self._format_weather()

        return response_text.strip() or "I'm not sure how to respond to that."

    def _format_datetime(self) -> str:
        now = datetime.now()
        return now.strftime("It's %A, %B %-d, %Y, %-I:%M %p.")

    async def _format_weather(self) -> str:
        data = await weather_service.get_current()
        if "error" in data:
            return "Sorry, I couldn't fetch the weather right now."
        return (
            f"It's {data['temp_f']} degrees and {data['description'].lower()}, "
            f"feels like {data['feels_like_f']}, humidity {data['humidity']} percent."
        )
