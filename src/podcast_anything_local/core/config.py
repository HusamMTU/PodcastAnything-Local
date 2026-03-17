"""Runtime configuration for the local backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in normal app runtime
    load_dotenv = None


class ConfigError(RuntimeError):
    """Raised when runtime configuration is invalid."""


def _read_env(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    return value or default


def _optional_env(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    return value or None


def _read_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    app_name: str
    data_dir: Path
    database_path: Path
    jobs_dir: Path
    web_extractor: str
    rewrite_style: str
    openai_base_url: str
    openai_api_key: str | None
    openai_model: str
    tts_provider: str
    elevenlabs_api_key: str | None
    elevenlabs_model_id: str
    elevenlabs_output_format: str
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "marin"
    openai_tts_voice_b: str = "cedar"
    openai_tts_response_format: str = "wav"
    elevenlabs_voice_id: str | None = None
    elevenlabs_voice_id_b: str | None = None

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    if load_dotenv is not None:
        load_dotenv()

    data_dir = Path(_read_env("DATA_DIR", "./data")).expanduser().resolve()
    database_path = Path(_read_env("DATABASE_PATH", str(data_dir / "app.db"))).expanduser()
    database_path = database_path.resolve()
    jobs_dir = Path(_read_env("JOBS_DIR", str(data_dir / "jobs"))).expanduser().resolve()

    tts_provider = _read_env("TTS_PROVIDER", "openai").lower()
    if tts_provider not in {"wave", "elevenlabs", "openai"}:
        raise ConfigError("TTS_PROVIDER must be one of: wave, elevenlabs, openai")

    web_extractor = _read_env("WEB_EXTRACTOR", "auto").lower()
    if web_extractor not in {"auto", "trafilatura", "bs4"}:
        raise ConfigError("WEB_EXTRACTOR must be one of: auto, trafilatura, bs4")

    openai_tts_response_format = _read_env("OPENAI_TTS_RESPONSE_FORMAT", "wav").lower()
    if openai_tts_response_format not in {"wav", "mp3", "flac", "aac", "opus", "pcm"}:
        raise ConfigError(
            "OPENAI_TTS_RESPONSE_FORMAT must be one of: wav, mp3, flac, aac, opus, pcm"
        )

    return Settings(
        app_env=_read_env("APP_ENV", "development"),
        app_name=_read_env("APP_NAME", "Podcast Anything Local"),
        data_dir=data_dir,
        database_path=database_path,
        jobs_dir=jobs_dir,
        web_extractor=web_extractor,
        rewrite_style=_read_env("REWRITE_STYLE", "podcast"),
        openai_base_url=_read_env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_api_key=_optional_env("OPENAI_API_KEY"),
        openai_model=_read_env("OPENAI_MODEL", "gpt-4o-mini"),
        tts_provider=tts_provider,
        elevenlabs_api_key=_optional_env("ELEVENLABS_API_KEY"),
        elevenlabs_model_id=_read_env("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        elevenlabs_output_format=_read_env("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"),
        openai_tts_model=_read_env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        openai_tts_voice=_read_env("OPENAI_TTS_VOICE", "marin"),
        openai_tts_voice_b=_read_env("OPENAI_TTS_VOICE_B", "cedar"),
        openai_tts_response_format=openai_tts_response_format,
        elevenlabs_voice_id=_optional_env("ELEVENLABS_VOICE_ID"),
        elevenlabs_voice_id_b=_optional_env("ELEVENLABS_VOICE_ID_B"),
    )
