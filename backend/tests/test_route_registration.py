from backend.main import app


EXPECTED_MOUNTED_ROUTES = {
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/api/catalog/summary"),
    ("GET", "/api/catalog/get-json-catalog"),
    ("GET", "/api/catalog/grouped"),
    ("GET", "/artist-spotlight/artists-by-genre"),
    ("GET", "/artist-spotlight/artist-tracks"),
    ("GET", "/artist-spotlight/artist-summary"),
    ("POST", "/artist-spotlight/play"),
    ("GET", "/artist-spotlight/radio-set"),
    ("POST", "/artist-spotlight/play-radio"),
    ("GET", "/artist-spotlight/artist-story"),
    ("POST", "/artist-spotlight/play-artist-story"),
    ("GET", "/playback/status"),
    ("POST", "/playback/client-diagnostic"),
    ("POST", "/playback/narration-finished"),
    ("POST", "/playback/track-finished"),
    ("GET", "/supabase/decade-genre/play-first"),
    ("GET", "/supabase/decade-genre/play-sequence"),
    ("POST", "/supabase/decade-genre/next"),
    ("GET", "/supabase/decade-genre/get-sequence"),
    ("POST", "/supabase/decade-genre/get-favorites"),
    ("GET", "/supabase/collections/play-collection-sequence"),
    ("GET", "/playback/decade-genre"),
    ("POST", "/playback/play-track"),
    ("GET", "/playback/flags-status"),
    ("POST", "/playback/start"),
    ("POST", "/playback/pause"),
    ("POST", "/playback/resume"),
    ("POST", "/playback/stop"),
    ("POST", "/playback/skip"),
    ("POST", "/playback/reset"),
    ("GET", "/api/auth/spotify/login"),
    ("GET", "/api/auth/spotify/callback"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/supabase/signup"),
    ("GET", "/api/auth/marketing-preference"),
    ("POST", "/api/auth/marketing-preference"),
    ("POST", "/api/auth/supabase/session"),
    ("POST", "/api/create-checkout-session"),
    ("POST", "/api/create-2027-promo-checkout-session"),
    ("POST", "/api/create-billing-portal-session"),
    ("GET", "/api/verify-subscription"),
    ("GET", "/api/subscription-status"),
    ("POST", "/api/webhooks/stripe"),
    ("POST", "/api/webhooks/resend"),
    ("POST", "/api/feedback/"),
    ("GET", "/supabase/collections/get-sequence"),
    ("GET", "/music-docuseries/collections"),
    ("GET", "/music-docuseries/items"),
    ("POST", "/music-docuseries/play"),
}


REMOVED_CACHE_OAUTH_PATHS = {
    "/spotify/debug-config",
    "/spotify/authorize",
    "/spotify/callback",
    "/spotify/whoami",
    "/spotify/cache-check",
}


def test_application_import_and_route_registration_are_unchanged():
    registered_routes = {
        (method, route.path)
        for route in app.routes
        if (methods := getattr(route, "methods", None))
        for method in methods
        if method not in {"HEAD", "OPTIONS"}
    }

    assert registered_routes == EXPECTED_MOUNTED_ROUTES
    assert "/api/auth/me" in {path for _, path in registered_routes}
    assert "/api/auth/supabase/signup" in {path for _, path in registered_routes}
    assert "/api/auth/supabase/session" in {path for _, path in registered_routes}
    assert REMOVED_CACHE_OAUTH_PATHS.isdisjoint(
        {path for _, path in registered_routes}
    )
