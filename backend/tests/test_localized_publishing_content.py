from datetime import UTC,datetime
from types import SimpleNamespace
import pytest
from backend.studio.localized_publishing_content import approve,approved_package,prepare_draft,validate_package
PARTS=("intro","story","outro")
def pack(lang="en",story="Story text."):
 text={"intro":"Intro text.","story":story,"outro":"Outro text."};return {"schema_version":1,"language_code":lang,"narration":{p:{"text":text[p],"caption_cues":[{"start_ms":0,"end_ms":1,"text":text[p]}]} for p in PARTS},"youtube":{"title":"Title","description":"Description","keywords":["music"],"chapters":[{"id":"intro","label":"Intro","segment":"intro","offset_ms":0}]}}
def rec():return SimpleNamespace(localized_publishing_content_json=None,localized_publishing_content_sha256=None,localized_publishing_content_source_sha256=None,localized_publishing_content_reviewed_at=None,localized_publishing_content_reviewed_by=None)
def identity():return {p:f"{p}-audio" for p in PARTS}
@pytest.mark.parametrize("lang",["en","es","pt-BR"])
def test_approval_all_locales(lang):
 r=rec();v=pack(lang);approve(r,v,language=lang,story_text="Story text.",reviewer="gary",reviewed_at=datetime.now(UTC),audio_identity=identity(),durations={p:1 for p in PARTS});assert approved_package(r,language=lang,story_text="Story text.",audio_identity=identity(),durations={p:1 for p in PARTS})==v
@pytest.mark.parametrize("field",["localized_publishing_content_json","localized_publishing_content_sha256","localized_publishing_content_source_sha256","localized_publishing_content_reviewed_at","localized_publishing_content_reviewed_by"])
def test_every_approval_field_fails_closed(field):
 r=rec();v=pack();approve(r,v,language="en",story_text="Story text.",reviewer="gary",reviewed_at=datetime.now(UTC),audio_identity=identity());setattr(r,field,None)
 with pytest.raises(RuntimeError):approved_package(r,language="en",story_text="Story text.",audio_identity=identity())
def test_digest_and_validation_rejections(tmp_path):
 r=rec();v=pack();approve(r,v,language="en",story_text="Story text.",reviewer="gary",reviewed_at=datetime.now(UTC),audio_identity=identity());
 with pytest.raises(RuntimeError):approved_package(r,language="en",story_text="Story text.",audio_identity={p:"changed" for p in PARTS})
 for mutate in (lambda x:x["narration"]["intro"].update(caption_cues=[]),lambda x:x["youtube"].update(keywords=["x","X"]),lambda x:x["youtube"].update(chapters=[{"id":"x","label":"","segment":"bad","offset_ms":"0"}])):
  x=pack();mutate(x)
  with pytest.raises(ValueError):validate_package(x,language="en",story_text="Story text.",durations={p:1 for p in PARTS})
 def adapter(source):assert source["story"]=="Story text.";return pack()
 out=tmp_path/'draft.json';report=tmp_path/'review.md';assert prepare_draft({"story":"Story text."},adapter,out,report)["language_code"]=="en";assert out.exists() and report.exists()
class _Session:
 def __init__(self,*_):self.added=[];self.committed=False
 def __enter__(self):return self
 def __exit__(self,*_):pass
 def add(self,x):self.added.append(x)
 def commit(self):self.committed=True

def test_cli_refusal_and_approval_both_source_types(tmp_path,monkeypatch):
 import backend.scripts.prepare_localized_publishing_content as cli
 input_path=tmp_path/'approved.json';input_path.write_text(__import__('json').dumps(pack()),encoding='utf-8')
 locale=SimpleNamespace(story_text='Story text.',tts_bucket='b',tts_key='k')
 monkeypatch.setattr(cli,'locale_for',lambda *_:locale)
 sessions=[]
 def factory(*_):x=_Session();sessions.append(x);return x
 with pytest.raises(SystemExit,match='Refusing'):cli.main(['--slug','s','--language','en'],session_factory=factory)
 for kind in ('music_docuseries','artist_story'):
  args=['--slug','s','--language','en','--source-type',kind,'--input',str(input_path),'--reviewer','gary','--approve']
  if kind=='artist_story':args.extend(['--source-id','1'])
  cli.main(args,session_factory=factory)
 assert len(sessions)==2 and all(x.committed for x in sessions)
def test_cli_draft_adapter_writes_review_artifacts(tmp_path,monkeypatch):
 import backend.scripts.prepare_localized_publishing_content as cli
 locale=SimpleNamespace(story_text='Story text.',tts_bucket='b',tts_key='k'); monkeypatch.setattr(cli,'locale_for',lambda *_:locale)
 cli.main(['--slug','s','--language','en','--draft'],session_factory=lambda *_:_Session(),draft_adapter=lambda source:pack(),work_root=tmp_path)
 assert (tmp_path/'s/review/localized_publishing/en.draft.json').exists();assert (tmp_path/'s/review/localized_publishing/en.review.md').exists()
def test_migration_dry_run_apply_and_idempotence(monkeypatch,capsys):
 import backend.scripts.migrate_localized_publishing_content as migration
 executed=[]
 class Conn:
  def execute(self,v):executed.append(str(v))
  def __enter__(self):return self
  def __exit__(self,*_):pass
 class Engine:
  def begin(self):return Conn()
 monkeypatch.setattr(migration,'engine',Engine());monkeypatch.setattr(migration.argparse.ArgumentParser,'parse_args',lambda *_:SimpleNamespace(apply=False));migration.main();assert 'Dry run' in capsys.readouterr().out
 monkeypatch.setattr(migration.argparse.ArgumentParser,'parse_args',lambda *_:SimpleNamespace(apply=True));migration.main();first=len(executed);migration.main();assert first==len(executed)//2

def test_artist_story_cli_uses_real_sql_resolution(tmp_path,monkeypatch):
 import backend.scripts.prepare_localized_publishing_content as cli
 from sqlmodel import SQLModel,Session,create_engine
 from backend.models.dbmodels import ArtistStory
 database=create_engine(f"sqlite:///{tmp_path / 'artist.db'}")
 SQLModel.metadata.create_all(database,tables=[ArtistStory.__table__])
 with Session(database) as session:
  session.add(ArtistStory(artist_id=77,language_code='es',story_text='Story text.',tts_bucket='bucket',tts_key='key'));session.commit()
 input_path=tmp_path/'approved.json';input_path.write_text(__import__('json').dumps(pack('es')),encoding='utf-8')
 monkeypatch.setattr(cli,'engine',database)
 cli.main(['--slug','ignored','--language','es','--source-type','artist_story','--source-id','77','--input',str(input_path),'--reviewer','gary','--approve'])
 with Session(database) as session:
  saved=session.exec(__import__('sqlmodel').select(ArtistStory).where(ArtistStory.artist_id==77)).one()
  assert saved.localized_publishing_content_reviewed_by=='gary'

def test_preparation_paths_never_call_upload_or_publish(tmp_path,monkeypatch):
 import backend.scripts.prepare_localized_publishing_content as cli
 calls=[]
 def forbidden(*_,**__):calls.append(True);raise AssertionError('must not upload or publish')
 monkeypatch.setattr(cli,'upload',forbidden,raising=False);monkeypatch.setattr(cli,'publish',forbidden,raising=False)
 value=pack();validate_package(value,language='en',story_text='Story text.')
 r=rec();approve(r,value,language='en',story_text='Story text.',reviewer='gary',reviewed_at=datetime.now(UTC),audio_identity=identity())
 prepare_draft({'story':'Story text.'},lambda _:value,tmp_path/'draft.json',tmp_path/'review.md')
 assert calls==[]