from types import SimpleNamespace
from pathlib import Path
from backend.studio.factory import ProductionExecution, ProductionSession, create_documentary_production_contract
from backend.studio.stations.prepare_documentary_hook import prepare_documentary_hooks, hook_key
from backend.studio.stations.render_hook_visual import run_hook_visual, HOOK_VISUAL_ARTIFACT

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
