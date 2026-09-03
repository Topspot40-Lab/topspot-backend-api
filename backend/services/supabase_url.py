"""Non-secret Supabase URL normalization shared by service clients."""


def normalize_supabase_url(url: str) -> str:
    """Give the SDK its canonical root URL without changing public URL builders."""
    return url.strip().rstrip("/") + "/"


def storage_endpoint_url(url: str) -> str:
    """Build the trailing-slash Storage API endpoint required by storage3."""
    return normalize_supabase_url(url) + "storage/v1/"
