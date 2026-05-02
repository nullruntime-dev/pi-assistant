from pathlib import Path

import numpy as np


_WINDOW_SAMPLES = 512   # Silero v4 expects exactly 512 samples per call at 16 kHz
_DEFAULT_THRESHOLD = 0.55


def _find_model_path() -> Path:
    """Locate the Silero VAD ONNX bundled with openwakeword. Avoids adding a
    standalone download — openwakeword is already a hard dependency."""
    import openwakeword  # type: ignore
    pkg_dir = Path(openwakeword.__file__).resolve().parent
    return pkg_dir / "resources" / "models" / "silero_vad.onnx"


class SileroVAD:
    """Per-window voice activity detection using Silero VAD (ONNX, no torch).

    Each call processes a 512-sample window of float32 audio at 16 kHz and
    returns a probability in [0, 1]. The LSTM state is carried across calls
    so the model uses recent context; call `reset()` between utterances.
    """

    def __init__(self, sample_rate: int = 16000, threshold: float = _DEFAULT_THRESHOLD):
        import onnxruntime as ort

        self._sample_rate = np.array(sample_rate, dtype=np.int64)
        self.threshold = threshold
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(_find_model_path()),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    @property
    def window_samples(self) -> int:
        return _WINDOW_SAMPLES

    def probability(self, window: np.ndarray) -> float:
        """Run one 512-sample window through the model. Returns speech prob."""
        if window.shape[-1] != _WINDOW_SAMPLES:
            raise ValueError(f"VAD window must be {_WINDOW_SAMPLES} samples, got {window.shape[-1]}")
        x = window.astype(np.float32, copy=False).reshape(1, _WINDOW_SAMPLES)
        out, self._h, self._c = self._session.run(
            None,
            {"input": x, "sr": self._sample_rate, "h": self._h, "c": self._c},
        )
        return float(out[0][0])

    def chunk_speech_prob(self, chunk: np.ndarray) -> float:
        """Score an arbitrary-length chunk by running it as 512-sample windows
        and returning the max probability. Trailing < 512 samples are dropped."""
        flat = chunk.reshape(-1)
        n_windows = flat.shape[0] // _WINDOW_SAMPLES
        if n_windows == 0:
            return 0.0
        best = 0.0
        for i in range(n_windows):
            start = i * _WINDOW_SAMPLES
            p = self.probability(flat[start:start + _WINDOW_SAMPLES])
            if p > best:
                best = p
        return best
