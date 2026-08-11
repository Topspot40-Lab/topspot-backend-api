"""Prepare or approve localized YouTube assets; never uploads."""
from __future__ import annotations
import argparse
from pathlib import Path

def main(argv:list[str]|None=None)->int:
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--slug",required=True,help="One production slug, or 'all'");parser.add_argument("--work-root",type=Path,default=Path("backend/studio/work"));parser.add_argument("--env-file",type=Path);parser.add_argument("--approve",action="store_true");parser.add_argument("--reviewer");args=parser.parse_args(argv)
 from backend.studio.youtube.publishing_package import LOCALIZED_TITLES,approve_review_package,prepare_review_package
 slugs=tuple(LOCALIZED_TITLES) if args.slug=="all" else (args.slug,)
 if args.approve:
  if not args.reviewer or not args.reviewer.strip():parser.error("--reviewer is required with --approve")
  for slug in slugs:
   factory=args.work_root.resolve()/slug/"factory"
   for language in ("en","es","pt-BR"):print(f"APPROVED {args.reviewer.strip()}: {approve_review_package(factory,language=language)}")
  print("No upload or YouTube network call occurred.");return 0
 if args.env_file:
  from dotenv import load_dotenv
  load_dotenv(args.env_file.resolve(),override=False)
 from sqlmodel import Session,select
 from backend.database import engine
 from backend.models.dbmodels import MusicDocuseries,MusicDocuseriesLocale
 with Session(engine) as session:
  for slug in slugs:
   documentary=session.exec(select(MusicDocuseries).where(MusicDocuseries.slug==slug)).first()
   if documentary is None or documentary.id is None:raise SystemExit(f"Music Docuseries not found: {slug}")
   locales=session.exec(select(MusicDocuseriesLocale).where(MusicDocuseriesLocale.docuseries_id==documentary.id)).all();rows={row.language_code:row for row in locales};factory=args.work_root.resolve()/slug/"factory"
   for language in ("en","es","pt-BR"):
    row=rows.get(language)
    if row is None or not row.story_text or not row.hook_text:raise SystemExit(f"Missing localized story or hook: {slug}/{language}")
    output=prepare_review_package(factory,slug=slug,language=language,story_text=row.story_text,hook_text=row.hook_text);print(f"REVIEW REQUIRED: {output}")
 print("No upload or YouTube network call occurred.");return 0
if __name__=="__main__":raise SystemExit(main())
