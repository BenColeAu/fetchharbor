import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_DIR = Path(os.getenv("FETCHHARBOR_MEDIA_MODEL_DIR", "/models"))
WHISPER_REPOSITORY = "Systran/faster-whisper-small"
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
ASSETS = {
    "kokoro-v1.0.onnx": (
        (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.1/kokoro-v1.0.onnx"
        ),
        "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    ),
    "voices-v1.0.bin": (
        (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.1/voices-v1.0.bin"
        ),
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
}


def download_verified(name: str, url: str, expected_hash: str) -> None:
    destination = MODEL_DIR / name
    if destination.is_file():
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if hmac_compare(digest, expected_hash):
            return
    with tempfile.NamedTemporaryFile(dir=MODEL_DIR, delete=False) as handle:
        temporary = Path(handle.name)
        with urllib.request.urlopen(url, timeout=120) as response:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    try:
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if not hmac_compare(digest, expected_hash):
            raise RuntimeError(f"Checksum mismatch for {name}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=WHISPER_REPOSITORY,
        revision=WHISPER_REVISION,
        local_dir=MODEL_DIR / "whisper-small",
        allow_patterns=[
            "config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    )
    for name, (url, digest) in ASSETS.items():
        download_verified(name, url, digest)


if __name__ == "__main__":
    main()
