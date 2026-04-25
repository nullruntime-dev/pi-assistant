import numpy as np
import openwakeword
from openwakeword import Model


class WakeWordDetector:
    """Detects wake word in audio stream with debouncing for accuracy."""

    def __init__(
        self,
        wake_word: str = "hey_jarvis",
        threshold: float = 0.6,
        consecutive_frames: int = 2,
    ):
        self.threshold = threshold
        self.wake_word = wake_word
        self.consecutive_frames = max(1, consecutive_frames)
        self._streak = 0
        self.last_score = 0.0

        model_paths = openwakeword.get_pretrained_model_paths()
        matching = [p for p in model_paths if wake_word in p]

        if not matching:
            available = sorted({p.split("/")[-1].rsplit(".", 1)[0] for p in model_paths})
            raise ValueError(
                f"Wake word '{wake_word}' not available. "
                f"openwakeword ships these pretrained models: {available}. "
                f"Set WAKE_WORD in .env to one of them, or train a custom model."
            )

        self.model = Model(wakeword_models=matching)
        self.model_names = list(self.model.models.keys())
        print(
            f"Wake word detector ready: '{wake_word}' "
            f"(threshold: {threshold}, consecutive frames: {self.consecutive_frames})"
        )
        print(f"Loaded models: {self.model_names}")

    def detect(self, audio_chunk: np.ndarray) -> bool:
        if audio_chunk.dtype == np.float32:
            audio_chunk = (audio_chunk * 32767).astype(np.int16)

        audio_chunk = audio_chunk.flatten()
        prediction = self.model.predict(audio_chunk)

        best_score = 0.0
        for model_name, score in prediction.items():
            if self.wake_word not in model_name:
                continue
            if score > best_score:
                best_score = score

        self.last_score = float(best_score)
        if best_score > self.threshold:
            self._streak += 1
            if self._streak >= self.consecutive_frames:
                print(f"Wake word detected: '{self.wake_word}' (score: {best_score:.2f})")
                self._streak = 0
                return True
        else:
            self._streak = 0

        return False

    def reset(self):
        """Reset internal state between activations."""
        self.model.reset()
        self._streak = 0

