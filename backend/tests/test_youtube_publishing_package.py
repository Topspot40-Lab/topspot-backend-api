from __future__ import annotations
import json
from pathlib import Path
from PIL import Image
from backend.studio.youtube.publishing_package import approve_review_package,prepare_review_package

def _assets(factory:Path)->None:
 (factory/"shared").mkdir(parents=True);(factory/"shared"/"opening.mp4").write_bytes(b"opening");Image.new("RGB",(1920,1080),"navy").save(factory/"shared"/"hook_visual.png")
 for language in ("en","es","pt-BR"):
  narration=factory/"delivery"/language/"narration";narration.mkdir(parents=True);(factory/"delivery"/language/"documentary.mp4").write_bytes(b"video")
  for part in ("hook","intro","story","outro"):(narration/f"{part}.mp3").write_bytes(b"audio")

def test_review_package_contains_valid_scheduler_assets(tmp_path:Path)->None:
 factory=tmp_path/"factory";_assets(factory);commands=[]
 def runner(command:list[str])->None:commands.append(command);Path(command[-1]).write_bytes(b"complete audio")
 output=prepare_review_package(factory,slug="fabulous_fifties",language="es",story_text="Primera oración. Segunda oración.",hook_text="**Hook (18 segundos):** Este es *el gancho*.",probe=lambda _:10.0,runner=runner)
 assert commands and commands[0][0]=="ffmpeg";captions=(output/"captions.vtt").read_text(encoding="utf-8");assert captions.startswith("WEBVTT");assert "Hook (18 segundos)" not in captions;assert "*" not in captions
 metadata=json.loads((output/"youtube.json").read_text(encoding="utf-8"));assert "años cincuenta" in metadata["title"];assert metadata["language_code"]=="es";assert (output/"thumbnail.png").stat().st_size<2097152

def test_approval_copies_all_reviewed_assets(tmp_path:Path)->None:
 source=tmp_path/"factory"/"publishing_review"/"en";source.mkdir(parents=True)
 names={"complete_audio.mp3","captions.vtt","thumbnail.png","youtube.json","chapters.txt"}
 for name in names:(source/name).write_bytes(b"approved")
 destination=approve_review_package(tmp_path/"factory",language="en");assert {path.name for path in destination.iterdir()}==names
