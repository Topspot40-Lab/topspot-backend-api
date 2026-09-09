from __future__ import annotations
import hashlib,json
from pathlib import Path
from PIL import Image
import pytest
from backend.studio.youtube.publishing_package import LOCALIZED_TITLES,approve_review_package,documentary_timing,prepare_review_package

class Response:
 def __init__(self,payload:dict):self.payload=payload
 def raise_for_status(self)->None:pass
 def json(self)->dict:return self.payload

def alignment(*_,data,**__)->Response:
 cursor=0.0;words=[]
 for word in data["text"].split():
  words.append({"text":word,"start":cursor,"end":cursor+.2,"loss":.01});cursor+=.25
 return Response({"words":words,"loss":.01})

def test_all_release_topics_have_three_localized_titles()->None:
 assert len(LOCALIZED_TITLES)>=27
 assert all(set(titles)=={"en","es","pt-BR"} for titles in LOCALIZED_TITLES.values())

def _assets(factory:Path)->None:
 (factory/"shared").mkdir(parents=True);(factory/"shared"/"opening.mp4").write_bytes(b"opening");Image.new("RGB",(1920,1080),"navy").save(factory/"shared"/"hook_visual.png")
 for language in ("en","es","pt-BR"):
  narration=factory/"delivery"/language/"narration";narration.mkdir(parents=True);(factory/"delivery"/language/"documentary.mp4").write_bytes(b"video")
  for part in ("hook","intro","story","outro"):(narration/f"{part}.mp3").write_bytes(b"audio")

def test_review_package_contains_valid_scheduler_assets(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
 monkeypatch.setenv("ELEVENLABS_API_KEY","test-key")
 factory=tmp_path/"factory";_assets(factory);commands=[]
 def runner(command:list[str])->None:
  commands.append(command);destination=Path(command[-1])
  if destination.suffix==".png":Image.new("RGB",(1920,1080),"navy").save(destination)
  else:destination.write_bytes(b"complete audio")
 def probe(path:Path)->float:return 57.0 if path.name=="documentary.mp4" else 10.0
 output=prepare_review_package(factory,slug="fabulous_fifties",language="es",story_text="Primera oración. Segunda oración.",hook_text="**Hook (18 segundos):** Este es *el gancho*.",probe=probe,runner=runner,alignment_requester=alignment)
 assert commands and commands[0][0]=="ffmpeg";captions=(output/"captions.vtt").read_text(encoding="utf-8");assert captions.startswith("WEBVTT");assert "Hook (18 segundos)" not in captions;assert "*" not in captions
 metadata=json.loads((output/"youtube.json").read_text(encoding="utf-8"));assert "años cincuenta" in metadata["title"];assert metadata["language_code"]=="es";assert (output/"thumbnail.png").stat().st_size<2097152

def test_approval_copies_all_reviewed_assets(tmp_path:Path)->None:
 source=tmp_path/"factory"/"publishing_review"/"en";source.mkdir(parents=True)
 names={"complete_audio.mp3","captions.vtt","thumbnail.png","youtube.json","chapters.txt"}
 for name in names:(source/name).write_bytes(b"approved")
 destination=approve_review_package(tmp_path/"factory",language="en");assert {path.name for path in destination.iterdir()}==names

def _legacy_v2_factory(factory: Path, language: str = "en") -> None:
 _assets(factory)
 narration = factory / "delivery" / language / "narration"
 hashes = {part: hashlib.sha256((narration / f"{part}.mp3").read_bytes()).hexdigest() for part in ("hook", "intro", "story", "outro")}
 (factory / "delivery" / language / "narration.inputs.json").write_text(json.dumps({"version": 2, "source_sha256": hashes}), encoding="utf-8")
 (factory / "shared" / "opening.mp4").unlink()

def test_verified_legacy_v2_reconstructs_deleted_intermediate_timing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
 factory = tmp_path / "factory"
 _legacy_v2_factory(factory)
 durations = {"hook": 25.959909, "intro": 7.012426, "story": 520.080544, "outro": 14.675011}
 def probe(path: Path) -> float:
  return 581.228005 if path.name == "documentary.mp4" else durations[path.stem]
 timing = documentary_timing(factory, language="en", probe=probe)
 assert timing.legacy_reconstructed is True
 assert timing.hook_start == 6.5
 assert timing.story_start == pytest.approx(41.472335)
 assert timing.expected_duration == pytest.approx(581.227890)
 assert timing.duration_delta == pytest.approx(0.000115)
 assert "Legacy reconstructed timing was used; verified duration delta: +0.000115s" in capsys.readouterr().out

@pytest.mark.parametrize(("language", "duration_delta"), (("en", 0.020795), ("es", -0.000476), ("pt-BR", 0.013174)))
def test_verified_legacy_v2_reconstructs_no_hook_transition_layout(tmp_path: Path, capsys: pytest.CaptureFixture[str], language: str, duration_delta: float) -> None:
 factory = tmp_path / "factory"
 _legacy_v2_factory(factory, language)
 durations = {"hook": 25.959909, "intro": 7.012426, "story": 520.080544, "outro": 14.675011}
 no_hook_expected_duration = 579.977890
 def probe(path: Path) -> float:
  return no_hook_expected_duration + duration_delta if path.name == "documentary.mp4" else durations[path.stem]
 timing = documentary_timing(factory, language=language, probe=probe)
 assert timing.legacy_reconstructed is True
 assert timing.story_start == pytest.approx(40.222335)
 assert timing.expected_duration == pytest.approx(no_hook_expected_duration)
 assert timing.duration_delta == pytest.approx(duration_delta)
 assert "Legacy reconstructed timing used no-hook-transition layout" in capsys.readouterr().out

def test_verified_legacy_v2_rejects_duration_mismatch(tmp_path: Path) -> None:
 factory = tmp_path / "factory"
 _legacy_v2_factory(factory)
 durations = {"hook": 25.959909, "intro": 7.012426, "story": 520.080544, "outro": 14.675011}
 def probe(path: Path) -> float:
  return 581.277891 if path.name == "documentary.mp4" else durations[path.stem]
 with pytest.raises(RuntimeError, match="Legacy-v2 reconstructed duration"):
  documentary_timing(factory, language="en", probe=probe)

def test_current_v3_does_not_reconstruct_when_opening_media_is_missing(tmp_path: Path) -> None:
 factory = tmp_path / "factory"
 _assets(factory)
 narration = factory / "delivery" / "en" / "narration"
 hashes = {part: hashlib.sha256((narration / f"{part}.mp3").read_bytes()).hexdigest() for part in ("hook", "intro", "story", "outro")}
 (factory / "delivery" / "en" / "narration.inputs.json").write_text(json.dumps({"version": 3, "source_sha256": hashes}), encoding="utf-8")
 (factory / "shared" / "opening.mp4").unlink()
 with pytest.raises(FileNotFoundError, match="Missing opening media"):
  documentary_timing(factory, language="en", probe=lambda _: 10.0)
