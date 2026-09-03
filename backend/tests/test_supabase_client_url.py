from backend.services.supabase_url import normalize_supabase_url, storage_endpoint_url


def test_normalize_supabase_url_adds_exactly_one_trailing_slash():
    assert normalize_supabase_url("https://project.supabase.co") == "https://project.supabase.co/"
    assert normalize_supabase_url("https://project.supabase.co/") == "https://project.supabase.co/"
    assert normalize_supabase_url(" https://project.supabase.co/// ") == "https://project.supabase.co/"


def test_storage_endpoint_has_the_sdk_required_trailing_slash():
    assert storage_endpoint_url("https://project.supabase.co") == "https://project.supabase.co/storage/v1/"
