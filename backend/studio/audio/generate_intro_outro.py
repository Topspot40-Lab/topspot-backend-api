from __future__ import annotations

import tempfile
from pathlib import Path

from backend.config.tts_config import TTS_PROFILES, MODEL_BY_LANG
from backend.services.supabase_storage import upload_bytes
from backend.services.tts.elevenlabs_tts import generate_tts_mp3


ASSETS = {
    "en": {
        "bucket": "audio-en",
        "intro": (
            "Welcome to TopSpot40 Music Docuseries, "
            "where we bring the stories behind the music to life."
        ),
        "outro": (
            "Thank you for joining us for TopSpot40 Music Docuseries. "
            "Discover all the stories behind the music at Top Spot Forty dot com. "
            "Until next time... keep the music playing."
        ),
    },
    "es": {
        "bucket": "audio-es",
        "intro": (
            "Bienvenidos a TopSpot40 Music Docuseries, "
            "donde damos vida a las historias detrás de la música."
        ),
        "outro": (
            "Gracias por acompañarnos en TopSpot40 Music Docuseries. "
            "Descubra todas las historias detrás de la música en "
            "Top Spot Forty punto com. "
            "Hasta la próxima... que la música siga sonando."
        ),
    },
    "pt-BR": {
        "bucket": "audio-ptbr",
        "intro": (
            "Bem-vindos ao TopSpot40 Music Docuseries, "
            "onde damos vida às histórias por trás da música."
        ),
        "outro": (
            "Obrigado por nos acompanhar no TopSpot40 Music Docuseries. "
            "Descubra todas as histórias por trás da música em "
            "Top Spot Forty ponto com. "
            "Até a próxima... continue deixando a música tocar."
        ),
    },
}


def generate_asset(
    *,
    language: str,
    bucket: str,
    kind: str,
    text: str,
) -> None:
    profile = TTS_PROFILES[language]["intro"]
    voice_id = profile["voice_id"]
    settings = profile.get("settings")
    model_id = MODEL_BY_LANG.get(language)

    key = f"youtube/{kind}.mp3"

    print("=" * 80)
    print(f"Generating YouTube {kind}")
    print(f"Language: {language}")
    print(f"Voice ID: {voice_id}")
    print(f"Bucket:   {bucket}")
    print(f"Key:      {key}")
    print(f"Text:     {text}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"{language}_{kind}.mp3"

        generate_tts_mp3(
            text=text,
            out_path=out_path,
            voice_id=voice_id,
            overwrite=True,
            play=False,
            settings=settings,
            model_id=model_id,
            language=language,
            timeout=(10.0, 300.0),
        )

        upload_bytes(
            bucket=bucket,
            key=key,
            data=out_path.read_bytes(),
            content_type="audio/mpeg",
        )

    print(f"✅ Uploaded {bucket}/{key}")


def main() -> None:
    for language, config in ASSETS.items():
        bucket = config["bucket"]

        generate_asset(
            language=language,
            bucket=bucket,
            kind="intro",
            text=config["intro"],
        )

        generate_asset(
            language=language,
            bucket=bucket,
            kind="outro",
            text=config["outro"],
        )

    print("=" * 80)
    print("Done.")
    print("Generated and uploaded 6 YouTube intro/outro assets.")


if __name__ == "__main__":
    main()
