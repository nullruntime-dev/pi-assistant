import numpy as np
from faster_whisper import WhisperModel


class SpeechToText:
    """Transcribe audio to text using Whisper."""

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        """
        Initialize Whisper model.

        Args:
            model_size: Model size (tiny, base, small, medium, large-v3)
                       For Pi 5: 'tiny' or 'base' recommended
            device: 'cpu' or 'cuda'
        """
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type="int8",  # Faster on CPU
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe audio to text.

        Args:
            audio: Audio samples (float32, mono)
            sample_rate: Sample rate of audio

        Returns:
            Transcribed text
        """
        # Ensure float32
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0

        # Transcribe
        segments, info = self.model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,  # Filter out silence
        )

        # Combine segments
        text = " ".join(segment.text.strip() for segment in segments)
        return text
