import numpy as np
import openwakeword
from openwakeword import Model


class WakeWordDetector:
    """Detects wake word in audio stream."""

    def __init__(self, wake_word: str = "hey_jarvis", threshold: float = 0.5):
        self.threshold = threshold
        self.wake_word = wake_word

        # Find model path for requested wake word
        model_paths = openwakeword.get_pretrained_model_paths()
        matching = [p for p in model_paths if wake_word in p]

        if matching:
            # Load specific model
            self.model = Model(wakeword_model_paths=matching)
            print(f"Wake word detector ready: '{wake_word}' (threshold: {threshold})")
        else:
            # Load all models, filter by name later
            print(f"Wake word '{wake_word}' not found, loading all models")
            self.model = Model()

        # Get model names for filtering
        self.model_names = list(self.model.models.keys())
        print(f"Loaded models: {self.model_names}")

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """
        Check if wake word detected in audio chunk.

        Args:
            audio_chunk: Audio samples (16kHz, mono, int16 or float32)

        Returns:
            True if wake word detected
        """
        # Ensure int16 format (openwakeword expects this)
        if audio_chunk.dtype == np.float32:
            audio_chunk = (audio_chunk * 32767).astype(np.int16)

        # Flatten if needed
        audio_chunk = audio_chunk.flatten()

        # Run prediction
        prediction = self.model.predict(audio_chunk)

        # Check scores for each model
        for model_name, score in prediction.items():
            if score > self.threshold:
                print(f"Wake word detected: {model_name} (score: {score:.2f})")
                return True

        return False

    def reset(self):
        """Reset internal state between activations."""
        self.model.reset()
