import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")

from backend.services import supabase_storage


class FakeBucket:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list(self, *args, **kwargs):
        path = kwargs.get("path", args[0] if args else "")
        offset = kwargs.get("offset")
        if offset is None and len(args) > 1:
            offset = args[1].get("offset", 0)
        self.calls.append((path, offset))
        return self.pages.get((path, offset), [])


class FakeStorage:
    def __init__(self, buckets):
        self.buckets = buckets

    def from_(self, bucket):
        return self.buckets[bucket]


class FakeSupabase:
    def __init__(self, buckets):
        self.storage = FakeStorage(buckets)


def configure(monkeypatch, buckets):
    monkeypatch.setattr(supabase_storage, "supabase", FakeSupabase(buckets))
    supabase_storage._folder_cache.clear()


def test_list_folder_keys_paginates_and_returns_full_keys(monkeypatch):
    first_page = [{"name": f"track-{n}.mp3"} for n in range(1000)]
    second_page = [{"name": "last.mp3"}]
    bucket = FakeBucket({("detail", 0): first_page, ("detail", 1000): second_page})
    configure(monkeypatch, {"audio-en": bucket})

    keys = supabase_storage.list_folder_keys("audio-en", "detail")

    assert "detail/track-0.mp3" in keys
    assert "detail/last.mp3" in keys
    assert bucket.calls == [("detail", 0), ("detail", 1000)]


def test_object_exists_cached_uses_exact_key_match(monkeypatch):
    bucket = FakeBucket({("intro", 0): [{"name": "1950s_tv_themes_01.mp3"}]})
    configure(monkeypatch, {"audio-en": bucket})

    assert supabase_storage.object_exists_cached("audio-en", "intro/1950s_tv_themes_01.mp3")
    assert not supabase_storage.object_exists_cached("audio-en", "intro/1950s_tv_themes_01.mp")
    assert not supabase_storage.object_exists_cached("audio-en", "intro/1950s_tv_themes_010.mp3")


def test_folder_cache_is_reused(monkeypatch):
    bucket = FakeBucket({("artist", 0): [{"name": "artist-id.mp3"}]})
    configure(monkeypatch, {"audio-en": bucket})

    assert supabase_storage.object_exists_cached("audio-en", "artist/artist-id.mp3")
    assert supabase_storage.object_exists_cached("audio-en", "artist/missing.mp3") is False
    assert bucket.calls == [("artist", 0)]


def test_folder_cache_isolated_by_bucket_and_folder(monkeypatch):
    en = FakeBucket({
        ("detail", 0): [{"name": "shared.mp3"}],
        ("artist", 0): [{"name": "artist.mp3"}],
    })
    es = FakeBucket({("detail", 0): [{"name": "es-only.mp3"}]})
    configure(monkeypatch, {"audio-en": en, "audio-es": es})

    assert supabase_storage.object_exists_cached("audio-en", "detail/shared.mp3")
    assert not supabase_storage.object_exists_cached("audio-es", "detail/shared.mp3")
    assert supabase_storage.object_exists_cached("audio-en", "artist/artist.mp3")
    assert en.calls == [("detail", 0), ("artist", 0)]
    assert es.calls == [("detail", 0)]
