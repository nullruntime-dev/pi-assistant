import tempfile
from pathlib import Path
import urllib.request
import tarfile

import numpy as np
import sounddevice as sd


PIPER_MODELS = {
    "lessac": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "amy": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    },
}


class TextToSpeech:
    """Convert text to speech using Piper TTS."""

    def __init__(self, voice: str = "lessac"):
        """
        Initialize Piper TTS.

        Args:
            voice: Voice name (lessac, amy)
        """
        self.voice_name = voice
        self._voice = None
        self._model_dir = Path.home() / ".cache" / "piper-voices"
        self._model_dir.mkdir(parents=True, exist_ok=True)

    def _download_model(self):
        """Download voice model if not present."""
        model_info = PIPER_MODELS.get(self.voice_name, PIPER_MODELS["lessac"])

        model_name = model_info["url"].split("/")[-1]
        model_path = self._model_dir / model_name
        config_path = self._model_dir / f"{model_name}.json"

        if not model_path.exists():
            print(f"Downloading Piper voice model: {model_name}...")
            urllib.request.urlretrieve(model_info["url"], model_path)
            print("Model downloaded.")

        if not config_path.exists():
            print("Downloading config...")
            urllib.request.urlretrieve(model_info["config_url"], config_path)

        return model_path, config_path

    def _get_voice(self):
        if self._voice is None:
            from piper import PiperVoice

            model_path, config_path = self._download_model()
            self._voice = PiperVoice.load(str(model_path), str(config_path), use_cuda=False)
            print(f"Piper TTS ready: {self.voice_name}")

        return self._voice

    def speak(self, text: str):
        """Synthesize and play audio directly."""
        voice = self._get_voice()

        # Synthesize - returns AudioChunk per sentence
        for chunk in voice.synthesize(text):
            sd.play(chunk.audio_float_array, chunk.sample_rate)
            sd.wait()
