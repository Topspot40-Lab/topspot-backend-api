"""Continuous Artist Radio publisher using shared state and duration block policy."""
from __future__ import annotations
import asyncio, logging, random
from sqlalchemy import text, bindparam
from backend.database import engine
from backend.services import artist_spotlight_eligibility as eligibility
from backend.services.audio_urls import resolve_audio_ref
from backend.services.block_builder import build_track_block
from backend.services.radio_runtime import narration_keys_for, short_detail_keys_for
from backend.state.narration import narration_done_event, track_done_event
from backend.state.playback_runtime import current_runtime, current_user_id
from backend.state.playback_state import begin_track, mark_playing, update_phase
logger = logging.getLogger(__name__)
ALLOWED_GENRES = ('country','pop','rock','rnb_soul','latin_global','blues_jazz','folk_acoustic')
class Row:
    def __init__(self, d): self.__dict__.update(d)


def choose_artist_for_set(available, wanted, *, shuffle=random.shuffle):
    """Choose randomly from the unplayed artists in the requested genre."""
    candidates = [artist for artist in available if artist['genre_slug'] == wanted]
    candidates = candidates or list(available)
    # A multi-genre artist has one candidate row per qualifying genre.  Select
    # each artist once, while retaining the selected genre on the returned row.
    unique_candidates = {}
    for candidate in candidates:
        unique_candidates.setdefault(candidate['artist_id'], candidate)
    candidates = list(unique_candidates.values())
    shuffle(candidates)
    return candidates[0]


def _artists(genres, language):
    """Return localized, playable Radio candidates from Program Mode's base pool."""
    base_rows = eligibility.featured_artist_eligibility_rows(
        genres=list(genres),
        min_tracks=3,
        featured_only=True,
        per_genre=True,
    )
    if not base_rows:
        return []
    artist_ids = [row['artist_id'] for row in base_rows]
    metadata = _radio_metadata(artist_ids, language)
    playable_genres = _playable_ranked_genres(artist_ids, list(genres))
    return [
        {**row, **metadata[row['artist_id']]}
        for row in base_rows
        if row['artist_id'] in metadata
        and (row['artist_id'], row['genre_slug']) in playable_genres
    ]


def _radio_metadata(artist_ids, language):
    """Return optional localized biography assets without filtering artists."""
    q = text('''SELECT a.id artist_id,a.artist_name,a.spotify_artist_id,a.artist_description,
      story.tts_bucket long_bucket,story.tts_key long_key,
      locale.tts_bucket short_bucket,locale.tts_key short_key
      FROM artist a
      LEFT JOIN artist_story story ON story.artist_id=a.id AND story.language_code=:lang
      LEFT JOIN artist_locale locale ON locale.artist_id=a.id AND locale.language_code=:lang
      WHERE a.id IN :artist_ids''').bindparams(bindparam('artist_ids', expanding=True))
    with engine.connect() as connection:
        return {
            row['artist_id']: dict(row)
            for row in connection.execute(q, {'artist_ids': artist_ids, 'lang': language}).mappings()
        }


def biography_keys_for_artist(artist, bio_length):
    """Use only the requested-language biography asset; never fall back to English."""
    if bio_length == 'short':
        return artist.get('short_bucket'), artist.get('short_key')
    return artist.get('long_bucket'), artist.get('long_key')


def _playable_ranked_genres(artist_ids, genres):
    q = text('''SELECT DISTINCT t.artist_id,g.slug genre_slug
      FROM track t JOIN track_ranking tr ON tr.track_id=t.id
      JOIN decade_genre dg ON dg.id=tr.decade_genre_id JOIN genre g ON g.id=dg.genre_id
      WHERE t.artist_id IN :artist_ids AND g.slug IN :genres
      AND t.spotify_track_id<>'' AND t.duration_ms>0''').bindparams(
        bindparam('artist_ids', expanding=True), bindparam('genres', expanding=True)
    )
    with engine.connect() as connection:
        return {
            (row['artist_id'], row['genre_slug'])
            for row in connection.execute(q, {'artist_ids': artist_ids, 'genres': genres}).mappings()
        }


def build_ranked_artist_track_query():
    return text('''SELECT DISTINCT t.id track_id,t.track_name,t.spotify_track_id,t.duration_ms,t.album_artwork,t.short_detail_tts_key,a.artist_name,a.spotify_artist_id,tr.id ranking_id,tr.ranking
      FROM track t JOIN artist a ON a.id=t.artist_id JOIN track_ranking tr ON tr.track_id=t.id
      JOIN decade_genre dg ON dg.id=tr.decade_genre_id JOIN genre g ON g.id=dg.genre_id
      WHERE t.artist_id=:id AND g.slug=:genre_slug AND t.spotify_track_id<>'' AND t.duration_ms>0''')


def _tracks(artist_id, genre_slug):
    with engine.connect() as connection:
        rows = connection.execute(
            build_ranked_artist_track_query(), {'id': artist_id, 'genre_slug': genre_slug}
        ).mappings().all()
        # The query is DISTINCT, but preserve the no-repeat invariant if a
        # driver or view still yields duplicate ranked track rows.
        unique_tracks = {}
        for row in rows:
            track = dict(row)
            unique_tracks.setdefault(track['track_id'], track)
        return list(unique_tracks.values())
async def _narrate(user,phase,track,ctx,bucket,key):
    if not bucket or not key:
        logger.warning('artist_radio_narration_skipped phase=%s reason=missing_asset_reference',phase)
        return False
    try: audio_url=resolve_audio_ref(bucket,key)
    except Exception:
        logger.warning('artist_radio_narration_skipped phase=%s reason=unresolvable_asset_reference',phase)
        return False
    update_phase(user,phase,is_playing=True,current_rank=track['ranking'],current_ranking_id=track['ranking_id'],track_name=track['track_name'],artist_name=track['artist_name'],context={**ctx,'bucket':bucket,'key':key,'audio_url':audio_url,'voice_style':'before'})
    logger.info('artist_radio_published_phase phase=%s track_name=%s artist_name=%s genre=%s set_number=%s set_position=%s set_size=%s spotify_track_id=%s',phase,track['track_name'],track['artist_name'],ctx.get('genre_name'),ctx.get('set_number'),ctx.get('block_position'),ctx.get('block_size'),ctx.get('spotify_track_id')); narration_done_event(user).clear(); await narration_done_event(user).wait(); return True
async def run_artist_radio_sequence(*,genres=None,genre='ALL',tts_language='en',detail_length='short',bio_length='short',**_):
    requested=list(genres or ([genre] if genre!='ALL' else ALLOWED_GENRES))
    invalid=[x for x in requested if x not in ALLOWED_GENRES]
    if invalid: raise ValueError('Artist Radio received unsupported genre slugs')
    selected=list(dict.fromkeys(requested))
    if detail_length not in ('off','short','long') or bio_length not in ('short','long'): raise ValueError('invalid Artist Radio narration choice')
    user,status=current_user_id(),current_runtime().status; status.stopped=status.cancel_requested=False
    mark_playing(user_id=user,mode='artist_radio',language=tts_language,context={'type':'artist_radio','programType':'RADIO_ARTIST','selected_genres':selected})
    pool=_artists(selected,tts_language); logger.info('artist_radio_selection genres=%s detail=%s bio=%s eligible_artist_count=%d',selected,detail_length,bio_length,len({x['artist_id'] for x in pool}))
    played_artists=set(); played_tracks=set(); set_no=0
    while pool and not status.stopped and not status.cancel_requested:
        available=[x for x in pool if x['artist_id'] not in played_artists]
        if not available: played_artists.clear(); available=list(pool); random.shuffle(available)
        wanted=selected[set_no % len(selected)]; artist=choose_artist_for_set(available,wanted)
        rows=_tracks(artist['artist_id'],artist['genre_slug']); fresh=[x for x in rows if x['track_id'] not in played_tracks] or rows
        chosen=[x[0].__dict__ for x in build_track_block([(Row(x),) for x in fresh],set_number=set_no+1)]
        if not chosen: played_artists.add(artist['artist_id']); continue
        set_no+=1; played_artists.add(artist['artist_id']); total=sum(x['duration_ms'] for x in chosen)
        base={'type':'artist_radio','mode':'artist_radio','programType':'RADIO_ARTIST','selected_genres':selected,'genre':artist['genre_slug'],'genre_slug':artist['genre_slug'],'genre_name':artist['genre_name'],'artist_id':artist['artist_id'],'artist_name':artist['artist_name'],'artist_set_number':set_no,'artist_set_size':len(chosen),'set_number':set_no,'block_size':len(chosen),'artist_bio_length':bio_length,'detail_length':detail_length}
        logger.info('artist_radio_chosen artist_id=%s artist_name=%s genre=%s set_number=%d set_size=%d total_duration_ms=%d',artist['artist_id'],artist['artist_name'],artist['genre_name'],set_no,len(chosen),total)
        bio_bucket,bio_key=biography_keys_for_artist(artist,bio_length)
        first_track=chosen[0]
        bio_context={**base,'artist_set_position':1,'block_position':1,'ranking_id':first_track['ranking_id'],'track_id':first_track['track_id'],'spotify_track_id':first_track['spotify_track_id'],'duration_ms':first_track['duration_ms'],'album_artwork':first_track['album_artwork']}
        if bio_bucket and bio_key and not await _narrate(user,'artist',first_track,bio_context,bio_bucket,bio_key):
            logger.warning('artist_radio_artist_skipped artist_id=%s reason=unresolvable_biography',artist['artist_id'])
            continue
        if not bio_bucket or not bio_key:
            logger.info('artist_radio_biography_skipped artist_id=%s language=%s reason=missing_localized_asset',artist['artist_id'],tts_language)
        for pos,track in enumerate(chosen,1):
            if status.stopped or status.cancel_requested:return
            ctx={**base,'artist_set_position':pos,'block_position':pos,'ranking_id':track['ranking_id'],'track_id':track['track_id'],'spotify_track_id':track['spotify_track_id'],'duration_ms':track['duration_ms'],'album_artwork':track['album_artwork']}
            if detail_length!='off':
                obj=Row(track); art=Row({'spotify_artist_id':track['spotify_artist_id']}); bucket,key=(short_detail_keys_for(lang=tts_language,track=obj) if detail_length=='short' else narration_keys_for(lang=tts_language,track=obj,artist=art)[:2])
                if bucket and key: await _narrate(user,'detail',track,ctx,bucket,key)
            update_phase(user,'track',is_playing=True,current_rank=track['ranking'],current_ranking_id=track['ranking_id'],track_name=track['track_name'],artist_name=track['artist_name'],duration_seconds=track['duration_ms']/1000,elapsed_seconds=0,context=ctx); begin_track(user,track['duration_ms']/1000)
            logger.info('artist_radio_published_phase phase=track track_name=%s artist_name=%s genre=%s set_number=%s set_position=%s set_size=%s spotify_track_id=%s',track['track_name'],track['artist_name'],ctx.get('genre_name'),ctx.get('set_number'),ctx.get('block_position'),ctx.get('block_size'),ctx.get('spotify_track_id')); track_done_event(user).clear(); await track_done_event(user).wait(); played_tracks.add(track['track_id'])
        logger.info('artist_radio_transition next_artist_set=%d',set_no+1)
