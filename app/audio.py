"""Ses dosyası okuma/yazma (ffmpeg) ve Demucs ile vokal ayırma."""
import subprocess
import threading

import numpy as np
import torch

_demucs_model = None
_demucs_name = None
_demucs_lock = threading.Lock()

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# htdemucs_ft: 4 ayrı ince ayarlı modelin birleşimi; daha temiz vokal, yaklaşık 4 kat yavaş.
SEPARATION_MODELS = {"htdemucs": "Hızlı", "htdemucs_ft": "Yüksek kalite"}
DEFAULT_SEPARATION = "htdemucs"


def decode(path, sr, channels):
    """Herhangi bir ses dosyasını float32 numpy dizisine çözer: (channels, samples)."""
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", str(channels), "-ar", str(sr), "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    audio = np.frombuffer(out, dtype=np.float32)
    return audio.reshape(-1, channels).T.copy()


def encode_mp3(audio, sr, path):
    """(channels, samples) float32 diziyi mp3 olarak yazar."""
    channels = audio.shape[0]
    pcm = np.clip(audio.T, -1, 1).astype(np.float32).tobytes()
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-y",
        "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
        "-codec:a", "libmp3lame", "-q:a", "3", str(path),
    ]
    subprocess.run(cmd, input=pcm, check=True)


def _get_demucs(name):
    global _demucs_model, _demucs_name
    if _demucs_name != name:
        from demucs.pretrained import get_model
        _demucs_model = None  # GPU belleğinde aynı anda tek ayırma modeli dursun
        if DEVICE == "cuda":
            torch.cuda.empty_cache()
        _demucs_model = get_model(name)
        _demucs_model.to(DEVICE).eval()
        _demucs_name = name
    return _demucs_model


def separate_vocals(path, model_name=DEFAULT_SEPARATION):
    """Şarkıdan vokali ayırır. Dönüş: (vokal 44.1k mono, örnekleme hızı)."""
    from demucs.apply import apply_model

    if model_name not in SEPARATION_MODELS:
        raise ValueError(f"Bilinmeyen ayırma modeli: {model_name}")
    with _demucs_lock:
        model = _get_demucs(model_name)
        wav = torch.from_numpy(decode(path, model.samplerate, model.audio_channels))
        ref = wav.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        wav = (wav - mean) / std
        with torch.no_grad():
            sources = apply_model(model, wav[None], device=DEVICE, shifts=1, split=True, overlap=0.25, progress=False)[0]
        sources = sources * std + mean
        vocals = sources[model.sources.index("vocals")].mean(0).cpu().numpy()
        if DEVICE == "cuda":
            torch.cuda.empty_cache()
    return vocals[None, :], model.samplerate


def resample_mono(audio, sr_from, sr_to):
    """Basit ve yeterince kaliteli yeniden örnekleme (scipy polyphase)."""
    from math import gcd
    from scipy.signal import resample_poly

    g = gcd(sr_from, sr_to)
    return resample_poly(audio, sr_to // g, sr_from // g).astype(np.float32)
