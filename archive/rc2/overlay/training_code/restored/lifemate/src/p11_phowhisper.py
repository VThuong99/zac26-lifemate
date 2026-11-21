"""Pinned PhoWhisper-medium inference for the P11 comparison."""

import hashlib
import os
import random
import resource
import time
import wave
from pathlib import Path

PHOWHISPER_WEIGHT_SHA256 = "699b8650035692ceb72db1d24c2879654e1cf9fa2d422a3bb14ac990b5141c59"


def read_wav(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 16000, 2):
            raise ValueError(f"Expected mono 16 kHz PCM16 WAV: {path}")
        frames = audio.getnframes()
        if frames == 0 or frames > 30 * 16000:
            raise ValueError(f"Expected nonempty audio no longer than 30 seconds: {path}")
        samples = np.frombuffer(audio.readframes(frames), dtype="<i2").astype(np.float32) / 32768
    return samples, frames / 16000


class PhoWhisperASR:
    def __init__(self, model_dir: Path, device: str = "cuda", num_threads: int = 4):
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        import numpy as np
        import torch
        from transformers import AutoProcessor, WhisperForConditionalGeneration

        if device not in ("cpu", "cuda") or num_threads < 1:
            raise ValueError("device must be cpu or cuda and num_threads positive")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        model_dir = Path(model_dir)
        digest = hashlib.sha256()
        with (model_dir / "pytorch_model.bin").open("rb") as weights:
            for block in iter(lambda: weights.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != PHOWHISPER_WEIGHT_SHA256:
            raise ValueError("PhoWhisper weights do not match the official pinned checkpoint")

        random.seed(20261030)
        np.random.seed(20261030)
        torch.manual_seed(20261030)
        if device == "cuda":
            torch.cuda.manual_seed_all(20261030)
        torch.use_deterministic_algorithms(True)
        torch.set_num_threads(num_threads)
        self.torch = torch
        self.device = device
        self.dtype = torch.float16 if device == "cuda" else torch.float32
        self.processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        self.model = WhisperForConditionalGeneration.from_pretrained(
            model_dir, dtype=self.dtype, local_files_only=True, attn_implementation="sdpa"
        ).to(device).eval()
        if device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()

    def transcribe(self, audio_path: Path) -> dict:
        torch = self.torch
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        samples, duration = read_wav(audio_path)
        inputs = self.processor(samples, sampling_rate=16000, return_tensors="pt",
                                return_attention_mask=True)
        features = inputs.input_features.to(device=self.device, dtype=self.dtype)
        attention = inputs.attention_mask.to(device=self.device)
        if self.device == "cuda":
            start_event, end_event = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start_event.record()
        with torch.inference_mode():
            output = self.model.generate(
                features, attention_mask=attention, language="vi", task="transcribe",
                do_sample=False, num_beams=1, max_length=224,
            )
        if self.device == "cuda":
            end_event.record()
            torch.cuda.synchronize()
            gpu_seconds = start_event.elapsed_time(end_event) / 1000
        else:
            gpu_seconds = None
        tokens = output[0].tolist()
        if len(tokens) >= 224 and tokens[-1] != self.processor.tokenizer.eos_token_id:
            raise ValueError(f"PhoWhisper reached the output token limit: {audio_path}")
        text = self.processor.batch_decode(output, skip_special_tokens=True)[0].strip()
        if not text:
            raise ValueError(f"PhoWhisper returned an empty transcript: {audio_path}")
        return {
            "text": text, "audio_seconds": duration, "seconds": time.perf_counter() - wall_started,
            "cpu_seconds": time.process_time() - cpu_started, "gpu_seconds": gpu_seconds,
            "output_tokens": len(tokens),
        }

    def resource_metrics(self) -> dict:
        return {
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "gpu_peak_allocated_bytes": (
                self.torch.cuda.max_memory_allocated() if self.device == "cuda" else None),
            "gpu_peak_reserved_bytes": (
                self.torch.cuda.max_memory_reserved() if self.device == "cuda" else None),
            "parameters_deduplicated": sum(parameter.numel() for parameter in self.model.parameters()),
        }
