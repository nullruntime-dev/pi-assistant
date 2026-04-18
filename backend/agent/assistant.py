import re
import google.generativeai as genai

from backend.services.music import music_player


class Assistant:
    """
    AI Assistant using Google Gemini.
    Handles user queries with music playback.
    """

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=self._get_system_instruction(),
        )

    def _get_system_instruction(self) -> str:
        return """You are a helpful voice assistant running on a Raspberry Pi.
Keep responses concise and conversational - they will be spoken aloud.
Aim for 1-3 sentences unless the user asks for detail.
Be friendly but efficient. Avoid markdown formatting, bullet points, or lists.

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

For all other queries, respond normally."""

    async def process(self, user_input: str) -> str:
        """Process user input and return response."""
        try:
            # Check for direct stop commands
            stop_words = ["stop", "pause", "quiet", "silence", "shut up", "stop music", "stop playing"]
            if any(word in user_input.lower() for word in stop_words):
                if music_player.is_playing():
                    music_player.stop()
                    return "Music stopped."

            # Get AI response
            response = await self._generate_response(user_input)

            # Check for music commands in response
            music_match = re.search(r'\[PLAY_MUSIC:\s*(.+?)\]', response)
            if music_match:
                query = music_match.group(1).strip()
                result = await music_player.play(query)
                return result

            stop_match = re.search(r'\[STOP_MUSIC\]', response)
            if stop_match:
                result = music_player.stop()
                return result

            return response

        except Exception as e:
            print(f"Agent error: {e}")
            return "Sorry, I encountered an error processing your request."

    async def _generate_response(self, user_input: str) -> str:
        """Generate response using Gemini."""
        import asyncio

        # Run sync API in thread
        response = await asyncio.to_thread(
            self.model.generate_content,
            user_input,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=256,
            ),
        )

        if response.text:
            return response.text

        return "I'm not sure how to respond to that."
