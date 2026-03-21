from fastapi import Query, APIRouter, Request, HTTPException, Cookie
from fastapi.responses import RedirectResponse, JSONResponse
from backend.isaiah.isaiah_spotify import exchange_code_for_token, get_user_profile, get_valid_access_token  # from spotify helper module
import os
from dotenv import load_dotenv
import stripe
from backend.isaiah.jwt_session import create_jwt_token, JWT_EXP_DELTA_SECONDS, decode_jwt_token
from backend.isaiah.isaiah_spotify import get_valid_access_token
from datetime import datetime, timedelta, timezone
#from main import supabase  # import your Supabase client
from supabase import create_client
import logging
from backend.isaiah.isaiah_helper import get_env_config, get_spotify_redirect_uri, get_frontend_url
import uuid


# Flag to switch between local dev and Netlify deployment
IS_LOCAL = False  # set False when deploying to Netlify, set True if running locally

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("topspot")


config = get_env_config()  # returns dict with COOKIE_DOMAIN, SECURE_COOKIE, ENV





# Supabase implementation for later use for storage and utilization of access tokens and refresh tokens 
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


SPOTIFY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")


# Redirect Spotify URI
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")


#router = APIRouter()
spotify_user_auth_router = APIRouter()
play_router = APIRouter()
stripe_router = APIRouter()



# Helper function of retrieivning or if user does not have topspot account, create
async def get_or_create_topspot_user(user_profile: dict):
    spotify_user_id = user_profile["id"]
    logger.info("Checking for existing TopSpot user with Spotify ID: %s", spotify_user_id)


    res = supabase.table("topspot_users") \
        .select("*") \
        .eq("spotify_user_id", spotify_user_id) \
        .execute()


    if res.data and len(res.data) > 0:
        # Update last login & display info
        logger.info("Found existing TopSpot user: %s", res.data[0])
        supabase.table("topspot_users") \
            .update({
                "display_name": user_profile.get("display_name"),
                "spotify_display_name": user_profile.get("display_name"),
                "spotify_country": user_profile.get("country"),
                "spotify_product": user_profile.get("product"),
                "last_login_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("spotify_user_id", spotify_user_id) \
            .execute()

        logger.info("✅ Updated TopSpot user with Spotify ID %s", spotify_user_id)
    
        return res.data[0]

    # Insert new user
    insert = supabase.table("topspot_users").insert({
        "auth_user_id": str(uuid.uuid4()),
        "spotify_user_id": spotify_user_id,
        "email": user_profile.get("email"),
        "display_name": user_profile.get("display_name"),
        "spotify_display_name": user_profile.get("display_name"),
        "spotify_country": user_profile.get("country"),
        "spotify_product": user_profile.get("product"),
        "role": "listener", # default permissions
    }).execute()

    

    print("Insert data:", insert.data)
    if not insert.data:
        logger.error("Failed to create TopSpot user: %s", insert.error)
        raise HTTPException(status_code=500, detail="User creation failed")

    return insert.data[0]




@spotify_user_auth_router.get("/spotify/login")
def spotify_login():
    # Redirect user to Spotify authorization URL with your client ID and redirect_uri (backend callback)
    from urllib.parse import urlencode

    client_id = SPOTIFY_CLIENT_ID
    #redirect_uri = "https://api.topspot40.com/api/auth/spotify/callback"
    #redirect_uri = "http://127.0.0.1:8000/api/auth/spotify/callback"
    redirect_uri = get_spotify_redirect_uri(local=IS_LOCAL)
    scopes = "user-read-private playlist-read-private user-read-email user-read-private user-read-playback-state user-modify-playback-state streaming" # "user-read-private playlist-read-private"
    params = {
        "client_id": client_id, # client_id
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "show_dialog": "true"
    }
    url = "https://accounts.spotify.com/authorize?" + urlencode(params)
    return RedirectResponse(url)



# SPOTIFY OAUTH CALLBACK 
@spotify_user_auth_router.get("/spotify/callback")
async def spotify_callback(request: Request):
    logger.critical("=== SPOTIFY CALLBACK ENTERED ===")

    logger.critical("Request headers: %s", dict(request.headers))


    code = request.query_params.get("code")
    if not code:
        logger.error("Spotify callback missing authorization code")
        raise HTTPException(status_code=400, detail="Missing code")
    logger.info("Spotify callback HIT! code=%s", code)
    print("Spotify callback HIT! code=", code)


    #redirect_uri = "https://api.topspot40.com/api/auth/spotify/callback"
    #redirect_uri = "https://localhost:5173/api/auth/spotify/callback"

    #THIS IS THE MAIN ONE JUST IN CASE
    #redirect_uri = "http://127.0.0.1:8000/api/auth/spotify/callback"


    redirect_uri = get_spotify_redirect_uri(local=IS_LOCAL)

    token_data = await exchange_code_for_token(code, redirect_uri)
    access_token = token_data["access_token"]

    refresh_token = token_data.get("refresh_token")   # sometimes only returned on first exchange
    expires_in = token_data.get("expires_in", 3600)

    # Calculate expiry time
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)


    user_profile = await get_user_profile(access_token)

    is_premium = user_profile.get("product") == "premium"
    #is_premium = await is_spotify_user_premium(code, redirect_uri)
    if not is_premium:
        logger.warning(f"User {user_profile.get('id')} is not Spotify Premium")
        #return RedirectResponse("https://topspot40.com/app/not-spotify-premium")
        return RedirectResponse("/not-spotify-premium") # "http://localhost:8000/app/not-spotify-premium"

    # created user session JWT here
    #user_id = user_profile["id"]

    # Find or create TopSpot40 user
    topspot_user = await get_or_create_topspot_user(user_profile)
    topspot_user_id = topspot_user["id"]

    if not topspot_user or "id" not in topspot_user:
        logger.error("TopSpot user creation failed. Profile=%s", user_profile)
        raise HTTPException(status_code=500, detail="Failed to create user")


    try:
        # Persist tokens in Supabase
        supabase.table("spotify_tokens").upsert({
            "user_id": topspot_user_id, # not user_id, the spotify_tokens table must reference to topspot users, not spotify users
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat(),
        }).execute()
        logger.info(f"Stored tokens for user {topspot_user_id} in Supabase")
    except Exception as e:
        logger.exception("Failed to persist tokens in Supabase")
        raise HTTPException(status_code=500, detail="Could not save Spotify tokens")
    

    # Generate JWT for session Cookie
    jwt_token = create_jwt_token(topspot_user_id) # not user_id, but topspot user id


    
    #redirect_response = RedirectResponse("http://localhost:8000/app/create-account")
    
    # pre-check if user already has subscribed to TopSpot40, before redirecting to 
    # either create-account route page (if user has not subscribed) or to
    # dashboard route page (if user has already subscribed to topspot40 AND has spotify premium)
    sub = supabase.table("subscriptions") \
        .select("*") \
        .eq("user_id", topspot_user_id) \
        .eq("status", "active") \
        .execute()
    

    if not sub.data or len(sub.data) == 0:
        redirect_url = f"{get_frontend_url(local=IS_LOCAL)}/create-account" # "http://localhost:8000/app/create-account"
    else:
        redirect_url = f"{get_frontend_url(local=IS_LOCAL)}/dashboard" # "http://localhost:8000/dashboard"
    redirect_response = RedirectResponse(redirect_url, status_code=302)


    logger.info(f"About to set JWT cookie for user {topspot_user_id}")
    #logger.critical("About to set cookie. JWT=%s", jwt_token)



    redirect_response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        #secure=False, # remove when in production
        #secure=True,  # True if HTTPS, uncomment this when in production
        secure=config["SECURE_COOKIE"],
        #samesite="lax", # might have to change to "none" in production
        samesite="none",# Uncomment for production
        max_age=JWT_EXP_DELTA_SECONDS,
        path="/",
        domain=config["COOKIE_DOMAIN"],
    )

    logger.info(f"Redirecting to {redirect_url} with JWT cookie {jwt_token}")


    return redirect_response
    
    


# Endpoint for frontend to get valid Spotify token
@spotify_user_auth_router.get("/spotify/sdk-token")
async def spotify_sdk_token(access_token: str = Cookie(None)): # should not fetch spotify user from frontend, SECURITY RISK
    """
    Returns a token specifically for the Web Playback SDK.
    """
    payload = decode_jwt_token(access_token)
    if not payload:
        raise HTTPException(status_code=401)
    user_id = payload["user_id"]
    token = await get_valid_access_token(user_id)
    return {"access_token": token}






#@spotify_user_auth_router.get("/spotify/refresh")
async def spotify_refresh(user_id: str):
    """
    Manually trigger a refresh for a given user_id.
    Frontend can call this before playback if the token is expired.
    """
    #new_token = await refresh_access_token(user_id)
    new_token = await get_valid_access_token(user_id)
    return {"access_token": new_token, "message": "Token refreshed"}







@spotify_user_auth_router.get("/spotify/token")
async def spotify_token(access_token: str = Cookie(None)):
    """
    Return a valid Spotify access token (auto-refresh if expired).
    Called by the frontend Spotify SDK.
    """

    payload = decode_jwt_token(access_token)
    if not payload:
        raise HTTPException(status_code=401)

    user_id = payload["user_id"]

    token = await get_valid_access_token(user_id)
    return {"access_token": token}












# Stripe endpoint
@stripe_router.post("/create-checkout-session")
async def create_checkout_session(access_token: str = Cookie(None)):
    stripe.api_key = os.environ.get("STRIPE_TEST_SECRET_KEY")
    stripe_price_id = os.getenv("STRIPE_TEST_PRICE_ID")
    

    if not stripe.api_key or not stripe_price_id:
        return {"error": "Stripe environment variables not set."}
    

    payload = decode_jwt_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid session")

    user_id = payload["user_id"]

    
    try:
        # Create Stripe checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": stripe_price_id,
                "quantity": 1,
            }],
            mode="subscription",
            client_reference_id=user_id, # stripe will know who made the subscription, saves us later pains of subscription recoveries
            metadata={ "topspot_user_id": user_id }, # extra key-value data from stripe
            #success_url="https://topspot40.com/app/success?session_id={CHECKOUT_SESSION_ID}", # This is for production!!!
            success_url=f"{get_frontend_url(local=IS_LOCAL)}/success?session_id={{CHECKOUT_SESSION_ID}}",
            #cancel_url="https://topspot40.com/app/create-account",
            cancel_url=f"{get_frontend_url(local=IS_LOCAL)}/create-account",
        )
        return {"url": session.url}

    except Exception as e:
        logger.exception("Stripe Checkout creation failed")
        return {"error": str(e)}
    






# verify if user has already subscribed to topspot40 app
@stripe_router.get("/verify-subscription")
async def verify_subscription(session_id: str, access_token: str = Cookie(None)):
    stripe.api_key = os.getenv("STRIPE_TEST_SECRET_KEY")
    logger.critical("=== VERIFY SUBSCRIPTION HIT ===")
    #logger.critical(f"Session ID received: {session_id}")
    #logger.critical(f"JWT cookie: {access_token}")



    payload = decode_jwt_token(access_token)
    #logger.critical(f"Decoded JWT payload: {payload}")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired JWT Session")
    user_id = payload["user_id"]
    
    


    try:
        # Retrieve the checkout session
        session = stripe.checkout.Session.retrieve(session_id)
        #logger.critical(f"Stripe session: {session}")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        if not subscription_id or not customer_id:
            raise HTTPException(status_code=400, detail="Invalid session")
        subscription = stripe.Subscription.retrieve(subscription_id)
        logger.critical(f"Stripe subscription: {subscription}")
        status = subscription.get("status")

        logger.critical(f"""
            WRITING SUBSCRIPTION TO DB:
            user_id: {user_id}
            customer_id: {customer_id}
            subscription_id: {subscription_id}
            status: {status}
            """)
        
        current_period_start = subscription.get("current_period_start")
        current_period_end = subscription.get("current_period_end")
        if current_period_start:
            current_period_start = datetime.fromtimestamp(current_period_start, tz=timezone.utc).isoformat()
        if current_period_end:
            current_period_end = datetime.fromtimestamp(current_period_end, tz=timezone.utc).isoformat()

        if status in ("active", "trialing"):
            supabase.table("subscriptions").upsert({
                "user_id": user_id,
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "stripe_price_id": subscription["items"]["data"][0]["price"]["id"],
                "status": status,
                "current_period_start": current_period_start,
                "current_period_end": current_period_end,
                "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            logger.critical("✅ Subscription successfully written to Supabase")

            # Also update topspot_users.stripe_customer_id so the user is linked to Stripe
            supabase.table("topspot_users").update({
                "stripe_customer_id": customer_id
            }).eq("id", user_id).execute()
            logger.info(f"✅ Updated topspot_users.stripe_customer_id for user {user_id}")



        #return {"status": status, "subscription_id": subscription_id}
        #return RedirectResponse(url=f"{get_frontend_url(local=IS_LOCAL)}/app/success?session_id={session_id}")
        return {
            "status": status,
            "subscription_id": subscription_id,
            "is_active": status in ("active", "trialing")
        }


    except Exception as e:
        logger.exception("Failed to verify Stripe subscription")
        raise HTTPException(status_code=500, detail=str(e))
    




# check if user has subscribed, adding a route for your frontend to query subscription status.
@stripe_router.get("/subscription-status")
async def get_subscription_status(access_token: str = Cookie(None)):
    logger.critical("=== SUBSCRIPTION STATUS HIT ===")
    #logger.critical("Cookie received: %s", access_token)


    payload = decode_jwt_token(access_token)
    #logger.critical("Decoded JWT payload: %s", payload)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired JWT Session")
    user_id = payload["user_id"]

    res = supabase.table("subscriptions").select("*").eq("user_id", user_id).maybe_single().execute()
    if not res.data:
        return {"is_subscribed": False}
        #return RedirectResponse(url="http://localhost:5173/app/create-account")

    status = res.data.get("status", "inactive")
    return {"is_subscribed": status in ("active", "trialing")}
    #return RedirectResponse(url="http://localhost:5173/dashboard")




# Stripe Webhook
"""
Edge case: if user accidentally clicks off the screen, 
or closes off tab, it does not write on Supabase, 
if requests fails, you LOSE the subscription, 
and it depends on the frontend, which is unreliable. So, 
we shall implement Stripe's webhooks. 
"""
@stripe_router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    logger.critical("🚨 Stripe webhook endpoint HIT")
    stripe.api_key = os.getenv("STRIPE_TEST_SECRET_KEY")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.exception("Webhook failed")
        return JSONResponse(status_code=400, content={"error": str(e)})

    event_type = event["type"]
    data = event["data"]["object"]

    logger.critical(f"🔥 Webhook event: {event_type}")

    try:
        # ✅ Checkout completed (initial subscription)
        if event_type == "checkout.session.completed":
            session = data

            user_id = session.get("metadata", {}).get("topspot_user_id")
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")

            if user_id and subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)

                current_period_start = datetime.fromtimestamp(
                    subscription["current_period_start"], tz=timezone.utc
                ).isoformat()

                current_period_end = datetime.fromtimestamp(
                    subscription["current_period_end"], tz=timezone.utc
                ).isoformat()

                supabase.table("subscriptions").upsert({
                    "user_id": user_id,
                    "stripe_customer_id": customer_id,
                    "stripe_subscription_id": subscription_id,
                    "stripe_price_id": subscription["items"]["data"][0]["price"]["id"],
                    "status": subscription["status"],
                    "current_period_start": current_period_start,
                    "current_period_end": current_period_end,
                    "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).execute()

                logger.critical("✅ Webhook wrote subscription")


                # Also update topspot_users.stripe_customer_id for the webhook flow
                supabase.table("topspot_users").update({
                    "stripe_customer_id": customer_id,
                    "is_active": True,
                }).eq("id", user_id).execute()
                logger.info(f"✅ Webhook updated topspot_users.stripe_customer_id for user {user_id}")


        # 💰 Renewal payments
        elif event_type == "invoice.payment_succeeded":
            subscription_id = data.get("subscription")

            supabase.table("subscriptions").update({
                "status": "active",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("stripe_subscription_id", subscription_id).execute()

            logger.critical("💰 Payment succeeded (renewal)")

        # 🔄 Subscription updates
        elif event_type == "customer.subscription.updated":
            subscription_id = data.get("id")

            supabase.table("subscriptions").update({
                "status": data.get("status"),
                "cancel_at_period_end": data.get("cancel_at_period_end", False),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("stripe_subscription_id", subscription_id).execute()

            logger.critical("🔄 Subscription updated")

        # ❌ Subscription canceled
        elif event_type == "customer.subscription.deleted":
            subscription_id = data.get("id")

            supabase.table("subscriptions").update({
                "status": "canceled",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("stripe_subscription_id", subscription_id).execute()

            logger.critical("❌ Subscription canceled")

    except Exception as e:
        logger.exception("Error processing webhook event")
        return JSONResponse(status_code=400, content={"error": str(e)})

    return JSONResponse({"status": "success"})


