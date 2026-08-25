"""Review-first localized YouTube package generation; never uploads."""
from __future__ import annotations
import json,re,shutil,subprocess,textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

LANGUAGE_NAMES={"en":"English","es":"Español","pt-BR":"Português (Brasil)"}
DOCUMENTARY_LABELS={"en":"Music Documentary","es":"Documental Musical","pt-BR":"Documentário Musical"}
LOCALIZED_TITLES={
 "fabulous_fifties":{"en":"The Fabulous Fifties","es":"Los fabulosos años cincuenta","pt-BR":"Os fabulosos anos cinquenta"},
 "swinging_sixties":{"en":"The Swinging Sixties","es":"Los vibrantes años sesenta","pt-BR":"Os vibrantes anos sessenta"},
 "seventies_decade_of_change":{"en":"The Seventies: A Decade of Change","es":"Los años setenta: una década de cambio","pt-BR":"Os anos setenta: uma década de mudanças"},
 "mtv_and_the_eighties":{"en":"MTV and the Eighties","es":"MTV y los años ochenta","pt-BR":"MTV e os anos oitenta"},
 "alternative_nation_nineties":{"en":"Alternative Nation: The Nineties","es":"Nación alternativa: los años noventa","pt-BR":"Nação alternativa: os anos noventa"},
 "music_in_the_new_millennium":{"en":"Music in the New Millennium","es":"La música en el nuevo milenio","pt-BR":"A música no novo milênio"},
 "story_behind_american_pie":{"en":"The Story Behind American Pie","es":"La historia detrás de American Pie","pt-BR":"A história por trás de American Pie"},
 "one_hit_wonders":{"en":"One-Hit Wonders","es":"Artistas de un solo éxito","pt-BR":"Artistas de um só sucesso"},
 "songs_banned_from_radio":{"en":"Songs Banned from Radio","es":"Canciones prohibidas en la radio","pt-BR":"Canções proibidas no rádio"},
 "woodstock":{"en":"Woodstock","es":"Woodstock","pt-BR":"Woodstock"},
 "beatles_vs_stones":{"en":"Beatles vs. Stones","es":"Beatles vs. Stones","pt-BR":"Beatles vs. Stones"},
 "elvis_vs_sinatra":{"en":"Elvis vs. Sinatra","es":"Elvis vs. Sinatra","pt-BR":"Elvis vs. Sinatra"},
 "country_traditionalists_vs_country_pop":{"en":"Country Traditionalists vs. Country Pop","es":"Tradicionalistas del country vs. country pop","pt-BR":"Tradicionalistas do country vs. country pop"},
 "ranchera_vs_norteno":{"en":"Ranchera vs. Norteño","es":"Ranchera vs. Norteño","pt-BR":"Ranchera vs. Norteño"},
 "vicente_fernandez_vs_antonio_aguilar":{"en":"Vicente Fernández vs. Antonio Aguilar","es":"Vicente Fernández vs. Antonio Aguilar","pt-BR":"Vicente Fernández vs. Antonio Aguilar"},
 "bossa_nova_vs_samba":{"en":"Bossa Nova vs. Samba","es":"Bossa Nova vs. Samba","pt-BR":"Bossa Nova vs. Samba"},
 "birth_of_rock_and_roll":{"en":"The Birth of Rock & Roll","es":"El nacimiento del rock and roll","pt-BR":"O nascimento do rock and roll"},
 "british_invasion":{"en":"The British Invasion","es":"La invasión británica","pt-BR":"A invasão britânica"},
 "rise_of_motown":{"en":"The Rise of Motown","es":"El auge de Motown","pt-BR":"A ascensão da Motown"},
 "birth_of_hip_hop":{"en":"The Birth of Hip-Hop","es":"El nacimiento del hip-hop","pt-BR":"O nascimento do hip-hop"},
 "napster_changes_music_forever":{"en":"Napster Changes Music Forever","es":"Napster cambia la música para siempre","pt-BR":"Napster muda a música para sempre"},
 "mtv_revolution":{"en":"The MTV Revolution","es":"La revolución de MTV","pt-BR":"A revolução da MTV"},
 "story_of_mariachi":{"en":"The Story of Mariachi","es":"La historia del mariachi","pt-BR":"A história do mariachi"},
 "birth_of_bossa_nova":{"en":"The Birth of Bossa Nova","es":"El nacimiento de la bossa nova","pt-BR":"O nascimento da bossa nova"},
 "story_of_samba":{"en":"The Story of Samba","es":"La historia de la samba","pt-BR":"A história do samba"},
 "story_of_tango":{"en":"The Story of Tango","es":"La historia del tango","pt-BR":"A história do tango"},
 "story_of_flamenco":{"en":"The Story of Flamenco","es":"La historia del flamenco","pt-BR":"A história do flamenco"},
    "don_cornelius": {
        "en": "Don Cornelius: The Soul Train Revolution",
        "es": "Don Cornelius: La revolución de Soul Train",
        "pt-BR": "Don Cornelius: A revolução do Soul Train",
    },
    "alan_freed": {
        "en": "Alan Freed: The DJ Who Named Rock & Roll",
        "es": "Alan Freed: El DJ que dio nombre al Rock & Roll",
        "pt-BR": "Alan Freed: O DJ que deu nome ao Rock & Roll",
    },
    "sam_phillips": {
        "en": "Sam Phillips: The Man Who Discovered Elvis",
        "es": "Sam Phillips: El hombre que descubrió a Elvis",
        "pt-BR": "Sam Phillips: O homem que descobriu Elvis",
    },
    "berry_gordy": {
        "en": "Berry Gordy: Building the Motown Sound",
        "es": "Berry Gordy: Construyendo el sonido Motown",
        "pt-BR": "Berry Gordy: Construindo o som da Motown",
    },
    "george_martin": {
        "en": "George Martin: The Fifth Beatle",
        "es": "George Martin: El quinto Beatle",
        "pt-BR": "George Martin: O quinto Beatle",
    },
    "quincy_jones": {
        "en": "Quincy Jones: The Producer Who Changed Pop Music",
        "es": "Quincy Jones: El productor que cambió la música pop",
        "pt-BR": "Quincy Jones: O produtor que mudou a música pop",
    },
    "phil_spector": {
        "en": "Phil Spector: The Wall of Sound",
        "es": "Phil Spector: El muro de sonido",
        "pt-BR": "Phil Spector: A parede de som",
    },
    "tom_dowd": {
        "en": "Tom Dowd: The Engineer Who Changed Recording Forever",
        "es": "Tom Dowd: El ingeniero que cambió la grabación para siempre",
        "pt-BR": "Tom Dowd: O engenheiro que mudou a gravação para sempre",
    },
    "ahmet_ertegun": {
        "en": "Ahmet Ertegun: The Atlantic Records Story",
        "es": "Ahmet Ertegun: La historia de Atlantic Records",
        "pt-BR": "Ahmet Ertegun: A história da Atlantic Records",
    },
    "clive_davis": {
        "en": "Clive Davis: The Executive with the Golden Ear",
        "es": "Clive Davis: El ejecutivo con oído de oro",
        "pt-BR": "Clive Davis: O executivo com ouvido de ouro",
    },
    "brian_epstein": {
        "en": "Brian Epstein: The Man Who Managed the Beatles",
        "es": "Brian Epstein: El hombre que dirigió a los Beatles",
        "pt-BR": "Brian Epstein: O homem que empresariou os Beatles",
    },
    "colonel_tom_parker": {
        "en": "Colonel Tom Parker: The Business of Elvis Presley",
        "es": "Coronel Tom Parker: El negocio de Elvis Presley",
        "pt-BR": "Coronel Tom Parker: O negócio de Elvis Presley",
    },
    "les_paul": {
        "en": "Les Paul: The Inventor Who Changed Recording Forever",
        "es": "Les Paul: El inventor que cambió la grabación para siempre",
        "pt-BR": "Les Paul: O inventor que mudou a gravação para sempre",
    },
    "sonidero_culture": {
        "en": "Sonidero Culture and Mexico's Love Affair with Cumbia",
        "es": "La cultura sonidera y el romance de México con la cumbia",
        "pt-BR": "A cultura sonidera e a paixão do México pela cúmbia",
    },
    "tejano_border_music": {
        "en": "Tejano Music: Born on Both Sides of the Border",
        "es": "Música tejana: nacida a ambos lados de la frontera",
        "pt-BR": "Música tejana: nascida dos dois lados da fronteira",
    },
    "border_blasters": {
        "en": "Border Blasters: The Powerful Radio Stations Broadcasting from Mexico",
        "es": "Border Blasters: Las poderosas emisoras de radio que transmiten desde México",
        "pt-BR": "Border Blasters: As poderosas emissoras de rádio que transmitem do México",
    },
}
DESCRIPTIONS={
 "en":"Explore {title}, a TopSpot40 music documentary about the artists, songs, sounds, and cultural changes that defined this unforgettable era.",
 "es":"Descubre {title}, un documental musical de TopSpot40 sobre los artistas, las canciones, los sonidos y los cambios culturales que definieron esta época inolvidable.",
 "pt-BR":"Conheça {title}, um documentário musical da TopSpot40 sobre os artistas, as canções, os sons e as mudanças culturais que definiram esta época inesquecível.",
}
CHAPTER_LABELS={"en":("Opening","The story","Closing"),"es":("Apertura","La historia","Cierre"),"pt-BR":("Abertura","A história","Encerramento")}
Probe=Callable[[Path],float];CommandRunner=Callable[[list[str]],None]

def media_duration(path:Path)->float:
 result=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],check=True,capture_output=True,text=True)
 return float(result.stdout.strip())
def run_command(command:list[str])->None:subprocess.run(command,check=True)

def prepare_review_package(factory:Path,*,slug:str,language:str,story_text:str,hook_text:str,probe:Probe=media_duration,runner:CommandRunner=run_command)->Path:
 if language not in LANGUAGE_NAMES:raise ValueError(f"Unsupported language: {language}")
 try:title=LOCALIZED_TITLES[slug][language]
 except KeyError as exc:raise ValueError(f"Missing approved localized title for {slug}/{language}") from exc
 delivery = factory / "delivery" / language
 narration = delivery / "narration"
 documentary = delivery / "documentary.mp4"

 required = (
     documentary,
     narration / "hook.mp3",
     narration / "intro.mp3",
     narration / "story.mp3",
     narration / "outro.mp3",
 )
 missing=[str(path) for path in required if not path.is_file() or path.stat().st_size==0]
 if missing:raise FileNotFoundError("Missing publishing inputs: "+", ".join(missing))
 durations={part:probe(narration/f"{part}.mp3") for part in ("hook","intro","story","outro")}
 opening_seconds = 6.5
 hook_start = opening_seconds
 story_start=hook_start+durations["hook"]+1.25+durations["intro"]+1.0;outro_start=story_start+durations["story"]+1.0
 output=factory/"publishing_review"/language;output.mkdir(parents=True,exist_ok=True)
 (output/"captions.vtt").write_text(_captions(hook_text=hook_text,story_text=story_text,hook_start=hook_start,hook_duration=durations["hook"],story_start=story_start,story_duration=durations["story"]),encoding="utf-8")
 labels=CHAPTER_LABELS[language];chapters=((0.0,labels[0]),(story_start,labels[1]),(outro_start,labels[2]));chapter_text="\n".join(f"{_chapter_time(seconds)} {label}" for seconds,label in chapters)+"\n"
 (output/"chapters.txt").write_text(chapter_text,encoding="utf-8")
 description=DESCRIPTIONS[language].format(title=title)+"\n\n"+chapter_text.rstrip()
 metadata={"title":f"{title} | {DOCUMENTARY_LABELS[language]}","description":description,"keywords":_keywords(title,language,slug),"language_code":language}
 (output/"youtube.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 thumbnail_source = output / "thumbnail_source.png"

 runner([
     "ffmpeg",
     "-y",
     "-ss",
     "8",
     "-i",
     str(documentary),
     "-frames:v",
     "1",
     str(thumbnail_source),
 ])

 _thumbnail(
     thumbnail_source,
     output / "thumbnail.png",
     title,
     language,
 )

 thumbnail_source.unlink(missing_ok=True)
 runner(["ffmpeg","-y","-i",str(documentary),"-vn","-codec:a","libmp3lame","-q:a","2",str(output/"complete_audio.mp3")])
 return output

def approve_review_package(factory:Path,*,language:str)->Path:
 source=factory/"publishing_review"/language;destination=factory/"publishing"/language;required=("complete_audio.mp3","captions.vtt","thumbnail.png","youtube.json","chapters.txt")
 missing=[name for name in required if not (source/name).is_file()]
 if missing:raise FileNotFoundError("Review package is incomplete: "+", ".join(missing))
 destination.mkdir(parents=True,exist_ok=True)
 for name in required:shutil.copy2(source/name,destination/name)
 return destination

def _captions(*,hook_text:str,story_text:str,hook_start:float,hook_duration:float,story_start:float,story_duration:float)->str:
 cues=_timed_cues(hook_text,hook_start,hook_duration)+_timed_cues(story_text,story_start,story_duration);lines=["WEBVTT",""]
 for start,end,text in cues:lines.extend((f"{_vtt_time(start)} --> {_vtt_time(end)}",text,""))
 return "\n".join(lines)
def _timed_cues(text:str,start:float,duration:float)->list[tuple[float,float,str]]:
 text=_clean_transcript(text);chunks=[]
 for sentence in re.split(r"(?<=[.!?])\s+",text):
  words=sentence.split();group_count=max(1,(len(words)+11)//12);group_size=max(1,(len(words)+group_count-1)//group_count)
  chunks.extend(" ".join(words[index:index+group_size]) for index in range(0,len(words),group_size))
 chunks=[chunk.strip() for chunk in chunks if chunk.strip()]
 if not chunks:raise ValueError("Caption transcript is empty")
 weights=[max(1,len(chunk.split())) for chunk in chunks];total=sum(weights);cursor=start;result=[]
 for index,(chunk,weight) in enumerate(zip(chunks,weights,strict=True)):
  end=start+duration if index==len(chunks)-1 else cursor+duration*weight/total;result.append((cursor,end,chunk));cursor=end
 return result
def _clean_transcript(text:str)->str:
 value=" ".join(text.split());value=re.sub(r"^(?:\*\*)?Hook\s*\([^)]*\)\s*:\s*(?:\*\*)?","",value,flags=re.IGNORECASE)
 return re.sub(r"(?<!\w)[*_]{1,2}|[*_]{1,2}(?!\w)","",value).strip()
def _thumbnail(source:Path,destination:Path,title:str,language:str)->None:
 from PIL import Image,ImageDraw,ImageEnhance,ImageOps
 with Image.open(source) as original:image=ImageOps.fit(original.convert("RGB"),(1280,720),method=Image.Resampling.LANCZOS)
 image=ImageEnhance.Contrast(image).enhance(1.08);overlay=Image.new("RGBA",image.size,(0,0,0,0));draw=ImageDraw.Draw(overlay)
 draw.rectangle((0,360,1280,720),fill=(0,0,0,0));draw.rounded_rectangle((960,32,1240,88),radius=18,fill=(175,24,24,235))
 small=_font(28);brand=_font(38);title_font=_font(84);draw.text((42,28),"TopSpot40.com",font=brand,fill=(255,205,48,255),stroke_width=2,stroke_fill="black")
 badge=LANGUAGE_NAMES[language];bbox=draw.textbbox((0,0),badge,font=small);draw.text((1100-(bbox[2]-bbox[0])/2,44),badge,font=small,fill="white")
 wrapped="\n".join(textwrap.wrap(title,width=25,break_long_words=False));draw.multiline_text((54,410),wrapped,font=title_font,fill="white",spacing=8,stroke_width=4,stroke_fill="black")
 Image.alpha_composite(image.convert("RGBA"),overlay).convert("RGB").quantize(colors=256).save(destination,optimize=True)
def _font(size:int)->Any:
 from PIL import ImageFont
 for path in (Path("C:/Windows/Fonts/arialbd.ttf"),Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
  if path.is_file():return ImageFont.truetype(str(path),size=size)
 return ImageFont.load_default()
def _keywords(title: str, language: str, slug: str) -> list[str]:
    common = {
        "en": ["music documentary", "music history"],
        "es": ["documental musical", "historia de la música"],
        "pt-BR": ["documentário musical", "história da música"],
    }

    history = {
        "fabulous_fifties",
        "swinging_sixties",
        "seventies_decade_of_change",
        "mtv_and_the_eighties",
        "alternative_nation_nineties",
        "music_in_the_new_millennium",
    }

    stories = {
        "story_behind_american_pie",
        "one_hit_wonders",
        "songs_banned_from_radio",
        "woodstock",
    }

    movements = {
        "birth_of_rock_and_roll",
        "british_invasion",
        "rise_of_motown",
        "birth_of_hip_hop",
        "napster_changes_music_forever",
        "mtv_revolution",
        "story_of_mariachi",
        "birth_of_bossa_nova",
        "story_of_samba",
        "story_of_tango",
        "story_of_flamenco",
    }

    people = {
        "don_cornelius",
        "alan_freed",
        "sam_phillips",
        "berry_gordy",
        "george_martin",
    }

    groups = {
        "en": (
            "music eras",
            "song stories",
            "music legends and rivalries",
            "music movements and revolutions",
            "people behind the music",
        ),
        "es": (
            "épocas musicales",
            "historias de canciones",
            "leyendas y rivalidades musicales",
            "movimientos y revoluciones musicales",
            "personas detrás de la música",
        ),
        "pt-BR": (
            "épocas musicais",
            "histórias de canções",
            "lendas e rivalidades musicais",
            "movimentos e revoluções musicais",
            "pessoas por trás da música",
        ),
    }

    group = groups[language]

    if slug in history:
        topic_group = group[0]
    elif slug in stories:
        topic_group = group[1]
    elif slug in movements:
        topic_group = group[3]
    elif slug in people:
        topic_group = group[4]
    else:
        topic_group = group[2]

    return [title, "TopSpot40", *common[language], topic_group]
def _vtt_time(seconds:float)->str:
 milliseconds=max(0,round(seconds*1000));hours,remainder=divmod(milliseconds,3600000);minutes,remainder=divmod(remainder,60000);secs,millis=divmod(remainder,1000);return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
def _chapter_time(seconds:float)->str:
 value=max(0,int(seconds));hours,remainder=divmod(value,3600);minutes,secs=divmod(remainder,60);return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
