from pathlib import Path
import urllib.request

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
    "hfc_female": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx.json",
    },
    "libritts_r": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx.json",
    },
    "ryan_high": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json",
    },
}


class TextToSpeech:
    """Convert text to speech using Piper TTS."""

    def __init__(self, voice: str = "amy", length_scale: float = 0.9):
        self.voice_name = voice if voice in PIPER_MODELS else "amy"
        self.length_scale = length_scale
        self._voice = None
        self._syn_config = None
        self._model_dir = Path.home() / ".cache" / "piper-voices"
        self._model_dir.mkdir(parents=True, exist_ok=True)

    def _download_model(self):
        model_info = PIPER_MODELS[self.voice_name]
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
            from piper import PiperVoice, SynthesisConfig

            model_path, config_path = self._download_model()
            self._voice = PiperVoice.load(str(model_path), str(config_path), use_cuda=False)
            self._syn_config = SynthesisConfig(length_scale=self.length_scale)
            print(f"Piper TTS ready: {self.voice_name} (length_scale={self.length_scale})")

        return self._voice

    def warmup(self):
        """Pre-load the voice model so first speech isn't delayed."""
        self._get_voice()

    def speak(self, text: str):
        """Synthesize full text and play. Blocks until done."""
        text = text.strip()
        if not text:
            return
        voice = self._get_voice()

        # Collect all chunks for this sentence, then play once — avoids the
        # audible gap between chunks that sd.play/sd.wait in a loop produces.
        parts = []
        sample_rate = None
        for chunk in voice.synthesize(text, syn_config=self._syn_config):
            parts.append(chunk.audio_float_array)
            sample_rate = chunk.sample_rate

        if not parts:
            return

        audio = parts[0] if len(parts) == 1 else np.concatenate(parts)
        sd.play(audio, sample_rate)
        sd.wait()
