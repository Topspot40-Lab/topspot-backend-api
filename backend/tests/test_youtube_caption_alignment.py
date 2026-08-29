from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.studio.youtube.caption_alignment import (
    AlignmentError,
    AlignedWord,
    aligned_words,
    format_vtt,
    vtt_cues,
)
from backend.studio.youtube.publishing_package import build_aligned_captions


class Response:
    def __init__(self, payload: dict): self.payload = payload
    def raise_for_status(self) -> None: pass
    def json(self) -> dict: return self.payload


def payload(text: str, *, gap_after: int | None = None, loss: float = .01) -> dict:
    cursor = 0.0; words = []
    for index, word in enumerate(text.split()):
        if gap_after == index: cursor += 1.5
        words.append({"text": word, "start": cursor, "end": cursor + .2, "loss": loss})
        cursor += .25
    return {"words": words, "loss": loss}


def test_aligned_captions_preserve_pauses_and_final_offsets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    hook = tmp_path / "hook.mp3"; story = tmp_path / "story.mp3"
    hook.write_bytes(b"hook"); story.write_bytes(b"story")
    def requester(*_, data, **__):
        return Response(payload(data["text"], gap_after=2 if data["text"].startswith("First") else None))
    vtt = build_aligned_captions(factory=tmp_path, hook_audio=hook, hook_text="First hook. After pause!", hook_start=6.5, hook_duration=4, story_audio=story, story_text="Story starts here.", story_start=18.5, story_duration=4, requester=requester)
    assert "00:00:06.500 --> 00:00:06.950" in vtt
    assert "00:00:08.500 --> 00:00:08.950" in vtt
    assert "00:00:18.500 -->" in vtt


def test_multilingual_alignment_and_cache_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"multilingual")
    calls: list[str] = []
    def requester(*_, data, **__):
        calls.append(data["text"]); return Response(payload(data["text"]))
    transcript = "A música mudou rápido. ¿Qué pasó después?"
    first = aligned_words(audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=10, requester=requester)
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    second = aligned_words(audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=10, requester=lambda **_: pytest.fail("cache miss"))
    assert [word.text for word in first] == [word.text for word in second] and len(calls) == 1


@pytest.mark.parametrize(("bad", "reason"), [
    ({"words": [{"text": "Sensitive word", "start": -1, "end": .5, "loss": .01}], "loss": .01}, "Alignment word 0 has a negative start"),
    ({"words": [{"text": "Sensitive word", "start": 1, "end": .5, "loss": .01}], "loss": .01}, "Alignment word 0 has end <= start"),
    ({"words": [{"text": "First", "start": 0, "end": .5, "loss": .01}, {"text": "Sensitive word", "start": .4, "end": .8, "loss": .01}], "loss": .01}, "Alignment word 1 overlaps the previous word by 0.100 seconds"),
])
def test_invalid_or_low_quality_alignment_fails_closed_with_safe_distinct_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: dict, reason: str) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    with pytest.raises(AlignmentError, match=re.escape(reason)) as exc_info:
        aligned_words(audio=audio, transcript="Hello", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(bad))
    assert "Sensitive word" not in str(exc_info.value)
    assert len(list((tmp_path / "cache").glob("*.quarantine.json"))) == 1


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ({}, "has no word timings"),
        ({"words": "not-a-list"}, "has no word timings"),
        ({"words": [{"text": "Hello", "start": 0, "end": .2}, {"text": "world", "start": .3, "end": .5}], "loss": "not-numeric"}, None),
        ({"words": [{"text": "Hello", "start": 0, "end": .2}, {"text": "world", "start": .1, "end": .3}]}, "overlaps"),
        ({"words": [{"text": "Hello", "start": 0, "end": 5.1}]}, "exceeds narration audio duration"),
    ],
)
def test_structural_and_timing_validation_is_fail_closed_but_loss_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict, reason: str | None,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    requester = lambda *_, **__: Response(response)
    if reason is None:
        assert len(aligned_words(audio=audio, transcript="Hello world", cache_dir=tmp_path / "cache", audio_duration=5, requester=requester)) == 2
    else:
        with pytest.raises(AlignmentError, match=reason):
            aligned_words(audio=audio, transcript="Hello world", cache_dir=tmp_path / "cache", audio_duration=5, requester=requester)


def test_rejected_valid_json_is_quarantined_and_rerun_does_not_call_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    bad = {"words": [{"text": "Hello", "start": 1, "end": .5, "loss": .01}], "loss": .01}
    with pytest.raises(AlignmentError, match="end <= start"):
        aligned_words(audio=audio, transcript="Hello", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(bad))
    quarantine = next((tmp_path / "cache").glob("*.quarantine.json"))
    assert json.loads(quarantine.read_text(encoding="utf-8")) == bad
    assert not quarantine.with_name(quarantine.name.replace(".quarantine", "")).exists()
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    with pytest.raises(AlignmentError, match="end <= start"):
        aligned_words(audio=audio, transcript="Hello", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: pytest.fail("network call"))


def test_valid_quarantined_alignment_is_promoted_and_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    cache = tmp_path / "cache"
    transcript = " ".join(f"word{index}" for index in range(72))
    from backend.studio.youtube.caption_alignment import _cache_key
    key = _cache_key(audio, transcript)
    cache.mkdir()
    quarantined = payload(transcript, loss=.019661)
    spaced_words: list[dict[str, object]] = []
    for word in quarantined["words"]:
        spaced_words.extend((word, {"text": " "}))
    quarantined["words"] = spaced_words[:-1]
    quarantined["words"][0]["loss"] = 1.884
    quarantine_path = cache / f"{key}.quarantine.json"
    quarantine_text = json.dumps(quarantined)
    quarantine_path.write_text(quarantine_text, encoding="utf-8")
    words = aligned_words(audio=audio, transcript=transcript, cache_dir=cache, audio_duration=40, requester=lambda *_, **__: pytest.fail("network call"))
    assert len(words) == 72 and words[0].loss == 1.884
    assert (cache / f"{key}.json").is_file()
    assert quarantine_path.read_text(encoding="utf-8") == quarantine_text


def test_quarantined_hook_and_story_alignments_promote_without_requesting_api(tmp_path: Path) -> None:
    from backend.studio.youtube.caption_alignment import _cache_key

    hook = tmp_path / "hook.mp3"; story = tmp_path / "story.mp3"
    hook.write_bytes(b"hook"); story.write_bytes(b"story")
    cache = tmp_path / "cache" / "caption_alignment"; cache.mkdir(parents=True)
    hook_text = "First hook sentence."
    story_text = "The story begins here."
    for audio, transcript in ((hook, hook_text), (story, story_text)):
        key = _cache_key(audio, transcript)
        (cache / f"{key}.quarantine.json").write_text(json.dumps(payload(transcript)), encoding="utf-8")

    vtt = build_aligned_captions(
        factory=tmp_path, hook_audio=hook, hook_text=hook_text, hook_start=0, hook_duration=5,
        story_audio=story, story_text=story_text, story_start=6, story_duration=5,
        requester=lambda *_, **__: pytest.fail("quarantined alignments must be promoted locally"),
    )
    assert "First hook sentence." in vtt and "The story begins here." in vtt
    assert len(list(cache.glob("*.json"))) == 4


def test_alignment_omits_alternating_whitespace_separators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = payload("First middle last")
    response["words"] = [item for word in response["words"] for item in (word, {"text": " "})]
    words = aligned_words(audio=audio, transcript="First middle last", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(response))
    assert [word.text for word in words] == ["First", "middle", "last"]


def test_alignment_omits_leading_and_trailing_whitespace_separators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = payload("First last", loss=.01)
    response["words"] = [{"text": " \t"}, *response["words"], {"text": "\n"}]
    response["words"][1]["loss"] = .5
    response["words"][2]["loss"] = .5
    words = aligned_words(audio=audio, transcript="First last", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(response))
    assert [word.loss for word in words] == [.5, .5]


@pytest.mark.parametrize("entry", [None, {"text": None}, {"text": 3}])
def test_alignment_rejects_non_string_word_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: object) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = payload("Hello")
    response["words"] = [entry]
    with pytest.raises(AlignmentError, match="contains an invalid word"):
        aligned_words(audio=audio, transcript="Hello", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(response))


def test_alignment_rejects_response_containing_only_separators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = {"words": [{"text": " "}, {"text": "\t"}], "loss": .01}
    with pytest.raises(AlignmentError, match="no spoken words"):
        aligned_words(audio=audio, transcript="Hello", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(response))


def test_alignment_checks_transcript_coverage_after_separator_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = payload("Hello world")
    response["words"].insert(1, {"text": " "})
    words = aligned_words(audio=audio, transcript="Hello world", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(response))
    assert " ".join(word.text for word in words) == "Hello world"


def test_alignment_rejects_lexical_transcript_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = payload("Hello world")
    with pytest.raises(AlignmentError, match="do not exactly cover"):
        aligned_words(audio=audio, transcript="Hello, there", cache_dir=tmp_path / "cache", audio_duration=5, requester=lambda *_, **__: Response(response))


@pytest.mark.parametrize(
    ("transcript", "alignment_text"),
    [
        ("Caf\u00e9\tROCK", "cafe rock"),  # case, whitespace, and diacritic
        ("can\u2019t", "cant"),  # apostrophe variant
        ("rock\u2011and\u2011roll", "rock-and-roll"),  # hyphen variant
        ("1,000", "1000"),  # numeric formatting
    ],
)
def test_alignment_accepts_harmless_typographic_coverage_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transcript: str, alignment_text: str,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    words = aligned_words(
        audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=5,
        requester=lambda *_, **__: Response(payload(alignment_text)),
    )
    assert " ".join(word.text for word in words) == " ".join(transcript.split())


@pytest.mark.parametrize(
    ("language", "transcript", "alignment_text"),
    [
        ("en", "alpha / beta / gamma", "alpha/beta /gamma"),
        ("es", "alfa / beta / gamma", "alfa/beta /gamma"),
        ("pt-BR", "alfa / beta / gama", "alfa/beta /gama"),
    ],
)
def test_catalog_punctuation_regrouping_preserves_supplied_transcript_in_vtt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str, transcript: str, alignment_text: str,
) -> None:
    """Regression shape from the three Ahmet Ertegun story quarantines: 5 source tokens, 2 aligned entries."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / f"{language}.mp3"; audio.write_bytes(language.encode())
    words = aligned_words(
        audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=5,
        requester=lambda *_, **__: Response(payload(alignment_text)),
    )
    assert len(transcript.split()) == 5
    assert len(alignment_text.split()) == 2
    assert " ".join(word.text for word in words) == transcript
    assert transcript in format_vtt(vtt_cues(words, offset=0))


@pytest.mark.parametrize(
    ("transcript", "alignment_text"),
    [
        ("one two three", "one three"),  # missing
        ("one two", "one two three"),  # extra
        ("one two three", "two one three"),  # reordered
        ("one two three", "one four three"),  # substituted
    ],
)
def test_alignment_rejects_genuine_lexical_coverage_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transcript: str, alignment_text: str,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    with pytest.raises(AlignmentError, match="do not exactly cover"):
        aligned_words(
            audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=5,
            requester=lambda *_, **__: Response(payload(alignment_text)),
        )


def _alignment_with_losses(losses: list[float], *, overall_loss: float = .01) -> tuple[str, dict]:
    transcript = " ".join(f"word{index}" for index in range(len(losses)))
    response = payload(transcript, loss=overall_loss)
    for word, loss in zip(response["words"], losses, strict=True):
        word["loss"] = loss
    return transcript, response


@pytest.mark.parametrize(
    ("transcript", "losses", "overall_loss"),
    [
        ("The music changed quickly.", [9.0, .01, 7.5, .01], 2.0),
        ("La música cambió rápido.", [.9, .9, .9, .9], .75),
        ("A música mudou rápido.", [5.0, 5.0, .01, 5.0], 4.25),
    ],
)
def test_all_catalog_languages_accept_loss_variation_with_numeric_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    transcript: str, losses: list[float], overall_loss: float,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    response = payload(transcript, loss=overall_loss)
    for word, loss in zip(response["words"], losses, strict=True):
        word["loss"] = loss
    words = aligned_words(audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=10, requester=lambda *_, **__: Response(response))
    diagnostics = [record.getMessage() for record in caplog.records if "quality diagnostics" in record.getMessage()]
    assert len(words) == len(losses)
    assert len(diagnostics) == 1
    assert all(name in diagnostics[0] for name in ("overall_loss=", "max_word_loss=", "high_loss_percentage=", "longest_high_loss_run="))
    assert transcript not in diagnostics[0] and "test-key" not in diagnostics[0]


def test_spanish_scale_distribution_is_accepted_without_slug_or_text_special_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio = tmp_path / "narration.mp3"; audio.write_bytes(b"audio")
    losses = [.01] * 1486
    for start in range(100, 1000, 100):
        for index in range(start, start + 3):
            losses[index] = .6
    losses[1050:1053] = [.6, 3.4729, .6]
    transcript, response = _alignment_with_losses(losses, overall_loss=.0404541112)
    words = aligned_words(audio=audio, transcript=transcript, cache_dir=tmp_path / "cache", audio_duration=400, requester=lambda *_, **__: Response(response))
    high_indexes = [index for index, word in enumerate(words) if word.loss > .5]
    gaps = [words[index].start - words[index - 1].end for index in high_indexes if index]
    assert len(words) == 1486
    assert len(high_indexes) == 30
    assert max(word.loss for word in words) == pytest.approx(3.4729)
    assert max(_consecutive_run_lengths(high_indexes)) == 3
    assert all(gap >= 0 for gap in gaps)


def _consecutive_run_lengths(indexes: list[int]) -> list[int]:
    runs: list[int] = []
    previous: int | None = None
    for index in indexes:
        if previous is None or index != previous + 1:
            runs.append(1)
        else:
            runs[-1] += 1
        previous = index
    return runs


def test_vtt_cues_are_ordered_readable_and_use_word_boundaries() -> None:
    words = [AlignedWord("One", 0, .2, .01), AlignedWord("two", .3, .5, .01), AlignedWord("three.", .6, .9, .01), AlignedWord("Next", 1.4, 1.7, .01), AlignedWord("sentence.", 1.8, 2.2, .01)]
    cues = vtt_cues(words, offset=12.25)
    assert cues == sorted(cues) and cues[0][:2] == (12.25, 13.15)
    assert all(len(line) <= 42 for _, _, text in cues for line in text.splitlines())
    assert "00:00:12.250 --> 00:00:13.150" in format_vtt(cues)


@pytest.mark.parametrize("cues", [
    [(1.0, 1.0, "text")],
    [(1.0, 2.0, "first"), (1.5, 2.5, "second")],
    [(-.1, .2, "text")],
    [(0.0001, 0.0004, "text")],
])
def test_invalid_or_overlapping_vtt_cues_fail_closed(cues: list[tuple[float, float, str]]) -> None:
    with pytest.raises(AlignmentError, match="Caption cues are empty, invalid, or out of order"):
        format_vtt(cues)
