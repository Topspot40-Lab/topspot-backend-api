"""Review-gated localized publishing content preparation; never uploads or publishes."""
from __future__ import annotations
import argparse,json
from collections.abc import Callable
from datetime import UTC,datetime
from pathlib import Path
from typing import Any
from sqlmodel import Session,select
from backend.database import engine
from backend.models.dbmodels import ArtistStory,MusicDocuseries,MusicDocuseriesLocale
from backend.studio.localized_publishing_content import approve,prepare_draft
DraftAdapter=Callable[[dict[str,Any]],dict[str,Any]]
def parser()->argparse.ArgumentParser:
 p=argparse.ArgumentParser();p.add_argument('--slug',required=True);p.add_argument('--language',required=True,choices=('en','es','pt-BR'));p.add_argument('--source-type',choices=('music_docuseries','artist_story'),default='music_docuseries');p.add_argument('--source-id',type=int);p.add_argument('--input',type=Path);p.add_argument('--reviewer');p.add_argument('--approve',action='store_true');p.add_argument('--draft',action='store_true');return p
def locale_for(session:Any,args:Any)->Any:
 if args.source_type=='music_docuseries':
  item=session.exec(select(MusicDocuseries).where(MusicDocuseries.slug==args.slug)).first()
  if not item:raise SystemExit('Music Docuseries not found')
  value=session.exec(select(MusicDocuseriesLocale).where(MusicDocuseriesLocale.docuseries_id==item.id).where(MusicDocuseriesLocale.language_code==args.language)).first()
 else:
  if args.source_id is None:raise SystemExit('--source-id is required for artist_story')
  value=session.exec(select(ArtistStory).where(ArtistStory.artist_id==args.source_id).where(ArtistStory.language_code==args.language)).first()
 if not value:raise SystemExit('Locale not found')
 return value
def main(argv:list[str]|None=None,*,session_factory:Callable[...,Any]=Session,draft_adapter:DraftAdapter|None=None,work_root:Path=Path('backend/studio/work'))->None:
 a=parser().parse_args(argv)
 if a.draft:
  if draft_adapter is None:raise SystemExit('Draft preparation requires an injected adapter')
  with session_factory(engine) as session:
   locale=locale_for(session,a); source={'slug':a.slug,'language_code':a.language,'story':locale.story_text,'audio_identity':{x:f'{locale.tts_bucket}/{locale.tts_key}/{x}' for x in ('intro','story','outro')}}
   base=work_root/a.slug/'review'/'localized_publishing';prepare_draft(source,draft_adapter,base/f'{a.language}.draft.json',base/f'{a.language}.review.md')
  return
 if not a.approve:raise SystemExit('Refusing database write without --approve')
 if not a.input or not a.reviewer:raise SystemExit('--input and --reviewer are required with --approve')
 package=json.loads(a.input.read_text(encoding='utf-8'))
 with session_factory(engine) as session:
  locale=locale_for(session,a); identity={x:f'{locale.tts_bucket}/{locale.tts_key}/{x}' for x in ('intro','story','outro')};approve(locale,package,language=a.language,story_text=locale.story_text,reviewer=a.reviewer,reviewed_at=datetime.now(UTC),audio_identity=identity);session.add(locale);session.commit()
 print('Approved localized publishing content saved; no upload or publishing occurred.')
if __name__=='__main__':main()