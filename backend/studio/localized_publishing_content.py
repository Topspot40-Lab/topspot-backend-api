"""Review-gated localized publishing-content preparation; never publishes."""
from __future__ import annotations
import hashlib,json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
SUPPORTED=("en","es","pt-BR"); PARTS=("intro","story","outro")
DraftAdapter=Callable[[dict[str,Any]],dict[str,Any]]
def canonical_json(value:dict[str,Any])->str:return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def sha256(value:dict[str,Any])->str:return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def _norm(s:str)->str:return " ".join(s.split())
def source_sha256(package:dict[str,Any],audio_identity:dict[str,str])->str:return sha256({"narration":{p:package["narration"][p]["text"] for p in PARTS},"audio_identity":audio_identity})
def validate_package(value:dict[str,Any],*,language:str,story_text:str,durations:dict[str,int]|None=None)->None:
 if language not in SUPPORTED or value.get("schema_version")!=1 or value.get("language_code")!=language:raise ValueError("Localized publishing package has invalid identity")
 narration=value.get("narration"); youtube=value.get("youtube")
 if not isinstance(narration,dict) or not isinstance(youtube,dict):raise ValueError("Localized publishing package is incomplete")
 for part in PARTS:
  segment=narration.get(part)
  if not isinstance(segment,dict) or not isinstance(segment.get("text"),str) or not segment["text"].strip() or not isinstance(segment.get("caption_cues"),list) or not segment["caption_cues"]:raise ValueError(f"Missing {part} caption cues")
  previous=0; reconstructed=[]
  for cue in segment["caption_cues"]:
   if not isinstance(cue,dict) or not isinstance(cue.get("text"),str) or not cue["text"].strip() or not isinstance(cue.get("start_ms"),int) or not isinstance(cue.get("end_ms"),int) or cue["start_ms"]<previous or cue["end_ms"]<=cue["start_ms"]:raise ValueError(f"Invalid {part} caption cue")
   if durations and cue["end_ms"]>durations[part]:raise ValueError(f"{part} caption exceeds narration duration")
   previous=cue["end_ms"]; reconstructed.append(cue["text"])
  if _norm(" ".join(reconstructed))!=_norm(segment["text"]):raise ValueError(f"{part} captions do not reconstruct transcript")
 if _norm(narration["story"]["text"])!=_norm(story_text):raise ValueError("Story transcript does not match canonical story_text")
 if not all(isinstance(youtube.get(k),str) and youtube[k].strip() for k in ("title","description")):raise ValueError("Missing localized YouTube metadata")
 keywords=youtube.get("keywords")
 if not isinstance(keywords,list) or not keywords or len({_norm(k).casefold() for k in keywords if isinstance(k,str)})!=len(keywords) or any(not isinstance(k,str) or not k.strip() for k in keywords):raise ValueError("Invalid keywords")
 chapters=youtube.get("chapters"); previous=-1; seen=set()
 if not isinstance(chapters,list) or not chapters:raise ValueError("Invalid chapters")
 for chapter in chapters:
  if not isinstance(chapter,dict) or not isinstance(chapter.get("id"),str) or not chapter["id"].strip() or chapter["id"] in seen or not isinstance(chapter.get("label"),str) or not chapter["label"].strip() or chapter.get("segment") not in PARTS or not isinstance(chapter.get("offset_ms"),int) or chapter["offset_ms"]<0:raise ValueError("Invalid chapters")
  if durations and chapter["offset_ms"]>durations[chapter["segment"]]:raise ValueError("Chapter exceeds narration duration")
  order=PARTS.index(chapter["segment"])*10**12+chapter["offset_ms"]
  if order<=previous:raise ValueError("Chapters are not ordered")
  previous=order;seen.add(chapter["id"])
 if chapters[0]["segment"]!="intro" or chapters[0]["offset_ms"]!=0:raise ValueError("First chapter must begin at intro zero")
def approve(record:Any,package:dict[str,Any],*,language:str,story_text:str,reviewer:str,reviewed_at:datetime,audio_identity:dict[str,str],durations:dict[str,int]|None=None)->None:
 if not reviewer.strip():raise ValueError("Reviewer is required")
 validate_package(package,language=language,story_text=story_text,durations=durations);record.localized_publishing_content_json=canonical_json(package);record.localized_publishing_content_sha256=sha256(package);record.localized_publishing_content_source_sha256=source_sha256(package,audio_identity);record.localized_publishing_content_reviewed_by=reviewer.strip();record.localized_publishing_content_reviewed_at=reviewed_at
def approved_package(record:Any,*,language:str,story_text:str,audio_identity:dict[str,str],durations:dict[str,int]|None=None)->dict[str,Any]:
 raw=getattr(record,"localized_publishing_content_json",None)
 if not raw or not getattr(record,"localized_publishing_content_sha256",None) or not getattr(record,"localized_publishing_content_source_sha256",None) or not getattr(record,"localized_publishing_content_reviewed_at",None) or not getattr(record,"localized_publishing_content_reviewed_by",None):raise RuntimeError("Localized publishing content is not approved")
 try:value=json.loads(raw)
 except json.JSONDecodeError as exc:raise RuntimeError("Localized publishing content is invalid JSON") from exc
 validate_package(value,language=language,story_text=story_text,durations=durations)
 if sha256(value)!=record.localized_publishing_content_sha256 or source_sha256(value,audio_identity)!=record.localized_publishing_content_source_sha256:raise RuntimeError("Localized publishing content digest mismatch")
 return value
def prepare_draft(source:dict[str,Any],adapter:DraftAdapter,output:Path,report:Path)->dict[str,Any]:
 package=adapter(dict(source)); output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({"source":source,"proposed_content":package},ensure_ascii=False,indent=2)+"\n",encoding="utf-8");report.write_text("# Localized publishing content review\n\nReview every transcript, cue, metadata field, keyword, and chapter before approval.\n",encoding="utf-8");return package