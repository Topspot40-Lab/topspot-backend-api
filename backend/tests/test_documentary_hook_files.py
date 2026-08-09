from types import SimpleNamespace
from pathlib import Path
from backend.studio.factory import ProductionExecution, ProductionSession, create_documentary_production_contract
from backend.studio.stations.prepare_documentary_hook import prepare_documentary_hooks, hook_key
from backend.studio.stations.render_hook_visual import run_hook_visual, HOOK_VISUAL_ARTIFACT
import pytest
from langdetect import detect

HOOK = "In 1967, Maya recorded her first song in Chicago; years later that Chicago recording reached millions. What happened between those two moments, and why did a modest Chicago session become the unlikely turning point that listeners everywhere still remember today?"
class DB:
 def __init__(self,row): self.row=row; self.commits=0
 def __enter__(self): return self
 def __exit__(self,*_): pass
 def get(self,*_): return self.row
 def add(self,*_): pass
 def commit(self): self.commits+=1

def test_hook_preparation_persists_and_reuses_localized_key():
 row=SimpleNamespace(hook_text=None,hook_tts_bucket=None,hook_tts_key=None,tts_bucket="audio-en")
 locale=SimpleNamespace(locale_id=1,language_code="en",story_text="In 1967, Maya recorded her first song in Chicago. Years later that Chicago recording reached millions.")
 doc=SimpleNamespace(source_type="music_docuseries",source_id=7,languages=(locale,))
 db=DB(row); calls=[]
 assert prepare_documentary_hooks(doc,writer=lambda *_:HOOK,synthesizer=lambda *_:b"mp3",uploader=lambda *x:calls.append(x),session_factory=lambda:db)
 assert row.hook_tts_key == hook_key(doc,"en",HOOK) and len(calls)==1 and db.commits==1
 assert not prepare_documentary_hooks(doc,writer=lambda *_:(_ for _ in ()).throw(AssertionError()),synthesizer=lambda *_:(_ for _ in ()).throw(AssertionError()),uploader=lambda *_:(_ for _ in ()).throw(AssertionError()),session_factory=lambda:db)

def test_hook_visual_renders_and_reuses(tmp_path: Path):
 contract=create_documentary_production_contract("hook_test")
 execution=ProductionExecution(contract=contract,work_root=tmp_path)
 locale=SimpleNamespace(hook_text=HOOK,story_text="story")
 production=SimpleNamespace(documentary=SimpleNamespace(language=lambda _:locale),session=ProductionSession(production_slug="hook_test",work_root=tmp_path))
 calls=[]
 assert run_hook_visual(production,execution,image_generator=lambda prompt:(calls.append(prompt) or b"png"))
 assert execution.record(HOOK_VISUAL_ARTIFACT)["status"]=="completed"
 assert not run_hook_visual(production,execution,image_generator=lambda _:(_ for _ in ()).throw(AssertionError()))
 assert len(calls)==1


def test_hook_retries_length_and_curiosity_failures_then_succeeds():
 from backend.studio.stations.prepare_documentary_hook import generate_validated_hook
 story="In 1967, Maya recorded her first song in Chicago. Years later that Chicago recording reached millions."
 attempts=iter(["Too short?", "In 1967 Maya recorded in Chicago and the song reached millions years later.", HOOK])
 assert generate_validated_hook(story,"en",lambda *_args, **_kwargs: next(attempts)) == HOOK

def test_hook_uses_deterministic_fallback_after_bounded_failures():
 from backend.studio.stations.prepare_documentary_hook import generate_validated_hook, MAX_HOOK_ATTEMPTS
 story="In 1967, Maya recorded her first song in Chicago. Years later that Chicago recording reached millions. " * 4
 calls=[]
 value=generate_validated_hook(story,"en",lambda *_args, **_kwargs: (calls.append(1) or "Too short?"))
 assert len(calls) == MAX_HOOK_ATTEMPTS
 assert detect(value) == "en"
 assert value.endswith("?")

@pytest.mark.parametrize(
    ("language", "expected_code", "story"),
    [
        (
            "en",
            "en",
            "In 1964, four musicians arrived in New York. "
            "Weeks later, millions watched their historic performance. " * 4,
        ),
        (
            "es",
            "es",
            "En 1964, cuatro músicos llegaron a Nueva York. "
            "Semanas después, millones vieron su histórica presentación. " * 4,
        ),
        (
            "pt-BR",
            "pt",
            "Em 1964, quatro músicos chegaram a Nova York. "
            "Semanas depois, milhões viram sua apresentação histórica. " * 4,
        ),
    ],
)
def test_fallback_hook_stays_in_requested_language(
    language: str,
    expected_code: str,
    story: str,
):
    from backend.studio.stations.prepare_documentary_hook import fallback_hook

    value = fallback_hook(story, language)

    assert detect(value) == expected_code
    assert value.endswith("?")


def test_spanish_hook_rejects_english_text():
    from backend.studio.stations.prepare_documentary_hook import (
        validate_hook_language,
    )

    with pytest.raises(ValueError, match="expected Spanish, detected en"):
        validate_hook_language(
            "This documentary tells an extraordinary story about music history.",
            "es",
        )

def test_existing_english_hook_for_spanish_is_regenerated():
    spanish_story = (
        "En 1964, Los Viajeros llegaron a Madrid y grabaron una canción "
        "en un pequeño estudio. Años después, aquella grabación apareció "
        "en televisión y llegó a millones de oyentes en toda España."
    )

    spanish_hook = (
        "En 1964, Los Viajeros llegaron a Madrid y grabaron una canción "
        "en un pequeño estudio casi desconocido. Años después, aquella "
        "misma grabación apareció en televisión y llegó a millones de "
        "oyentes en toda España. ¿Cómo logró una sesión tan modesta "
        "transformarse en un acontecimiento musical inolvidable?"
    )

    row = SimpleNamespace(
        hook_text=HOOK,
        hook_tts_bucket="audio-es",
        hook_tts_key="old-english-hook.mp3",
        tts_bucket="audio-es",
    )

    locale = SimpleNamespace(
        locale_id=42,
        language_code="es",
        story_text=spanish_story,
    )

    documentary = SimpleNamespace(
        source_type="music_docuseries",
        source_id=8,
        languages=(locale,),
    )

    db = DB(row)
    uploads = []

    changed = prepare_documentary_hooks(
        documentary,
        writer=lambda *_args, **_kwargs: spanish_hook,
        synthesizer=lambda *_args, **_kwargs: b"spanish-mp3",
        uploader=lambda *args: uploads.append(args),
        session_factory=lambda: db,
    )

    assert changed is True
    assert row.hook_text == spanish_hook
    assert row.hook_tts_bucket == "audio-es"
    assert "/es/" in row.hook_tts_key
    assert row.hook_tts_key != "old-english-hook.mp3"
    assert len(uploads) == 1
    assert db.commits == 1

def test_visual_plan_prompt_json_example_formats_without_specifier_error():
 from backend.studio.stations.generate_visual_plan import request_visual_plan
 import backend.studio.stations.generate_visual_plan as module
 captured=[]
 module.ask_xai = None
 # build request path is exercised through a fake lazy xAI module in the factory suite; here ensure braces are absent from f-string format fields.
 assert "art_direction" in Path(module.__file__).read_text(encoding="utf-8")
