import httpx
import re
from typing import Optional


def extract_event_ids_from_cookie(cookie: str) -> list[str]:
    """Parse all registered event IDs from a full Luma cookie string."""
    return re.findall(r'luma\.(evt-[A-Za-z0-9]+)\.registered-with=', cookie)


async def fetch_event_metadata(event_api_id: str, auth_token: str) -> dict:
    """Fetch name/date/location/guest_count and registration status for one event."""
    headers = _headers(auth_token)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            "https://api.lu.ma/event/get",
            params={"event_api_id": event_api_id},
            headers=headers,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        event = data.get("event") or data
        guest_data = data.get("guest_data") or {}
        return {
            "luma_id": event.get("api_id") or event_api_id,
            "name": event.get("name") or event.get("title") or event_api_id,
            "date": event.get("start_at") or "",
            "location": (
                (event.get("geo_address_info") or {}).get("full_address")
                or event.get("location") or ""
            ),
            "url": event.get("url") or "",
            "guest_count": data.get("guest_count") or 0,
            "approval_status": guest_data.get("approval_status") or "unknown",
        }


def _extract_slug(event_url: str) -> str:
    """
    Handles:
      https://lu.ma/etccannes
      https://luma.com/604mfd7g
      https://lu.ma/e/evt-abc123
      https://lu.ma/events/etccannes
      lu.ma/etccannes
      https://lu.ma/etccannes?tk=xxx
    """
    url = event_url.strip()
    url = re.sub(r'^https?://', '', url)
    url = re.sub(r'^www\.', '', url)

    if not (url.startswith('lu.ma') or url.startswith('luma.com')):
        raise ValueError(
            f"URL invalide : doit commencer par lu.ma ou luma.com (reçu : {event_url!r})"
        )

    path = re.sub(r'^(?:lu\.ma|luma\.com)/?', '', url)
    path = re.split(r'[?#]', path)[0].strip('/')

    if not path:
        raise ValueError(f"Aucun slug trouvé dans l'URL : {event_url!r}")

    skip = {'e', 'events', 'r', 'invite', 'calendar'}
    parts = path.split('/')
    slug = next((p for p in parts if p and p not in skip), parts[-1])
    return slug


def _headers(auth_token: str) -> dict:
    token = auth_token.strip()
    h = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "fr-FR,fr;q=0.9,en;q=0.8",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "origin": "https://lu.ma",
        "referer": "https://lu.ma/",
    }
    if token.startswith("Bearer "):
        h["authorization"] = token
    else:
        # Treat as raw cookie string; ensure key cookies are present
        h["cookie"] = token
    return h


async def fetch_event_and_guests(event_url: str, auth_token: str) -> dict:
    slug = _extract_slug(event_url)
    headers = _headers(auth_token)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # --- Get event metadata ---
        # Try url= first, then event_api_id= (luma.com short IDs need the second form)
        event_obj = None
        real_api_id = None

        for params in [{"url": slug}, {"event_api_id": slug}]:
            resp = await client.get(
                "https://api.lu.ma/event/get",
                params=params,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Response can be flat or nested under "event"
                event_obj = data.get("event") or data
                real_api_id = event_obj.get("api_id")
                if real_api_id:
                    break

        if not real_api_id:
            raise RuntimeError(
                "Impossible de récupérer l'événement. "
                "Vérifiez l'URL et votre token d'authentification Luma."
            )

        event_name = event_obj.get("name") or event_obj.get("title") or slug
        event_date = event_obj.get("start_at") or event_obj.get("start_time") or ""
        event_location = (
            (event_obj.get("geo_address_info") or {}).get("full_address")
            or event_obj.get("location")
            or ""
        )

        # --- Guest list (paginated) ---
        entries = []
        cursor = None

        while True:
            params = {
                "event_api_id": real_api_id,
                "pagination_limit": 100,
            }
            if cursor:
                params["pagination_cursor"] = cursor

            resp = await client.get(
                "https://api.lu.ma/event/get-guest-list",
                params=params,
                headers=headers,
            )

            if resp.status_code != 200:
                break

            data = resp.json()
            batch = data.get("entries") or data.get("guests") or []
            entries.extend(batch)

            if not data.get("has_more") or not batch:
                break
            cursor = data.get("next_cursor")

        return {
            "luma_id": real_api_id,
            "name": event_name,
            "date": event_date,
            "location": event_location,
            "guests": entries,
        }


def _parse_bio_short(bio_short: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Try to split 'Title @ Company' or 'Title at Company' into (title, company)."""
    if not bio_short:
        return None, None
    for sep in [" @ ", " at ", " chez ", " | "]:
        if sep in bio_short:
            parts = bio_short.split(sep, 1)
            return parts[0].strip() or None, parts[1].strip() or None
    return None, bio_short.strip() or None


def _normalize_handle(value: Optional[str]) -> Optional[str]:
    """Strip whitespace and ignore placeholder values users enter."""
    if not value:
        return None
    v = value.strip()
    # Common placeholder / junk values people enter in Luma forms
    JUNK = {"n", "na", "n/a", "no", "none", "yes", "x", "-", ".", "nan", "null", "@"}
    if v.lower() in JUNK or len(v) <= 1:
        return None
    return v


def _build_linkedin(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("http"):
        return raw.split("?")[0]
    # Luma stores paths like /in/xxx or /company/xxx
    if raw.startswith("/in/") or raw.startswith("/company/"):
        return f"https://linkedin.com{raw}"
    if "/" in raw:
        return f"https://linkedin.com{raw}" if raw.startswith("/") else f"https://linkedin.com/{raw}"
    return f"https://linkedin.com/in/{raw}"


def parse_guest(entry: dict) -> dict:
    """Normalize a Luma guest-list entry into our schema."""
    user = entry.get("user") or {}

    inferred_title, inferred_company = _parse_bio_short(user.get("bio_short"))

    return {
        "luma_user_id": entry.get("api_id") or user.get("api_id"),
        "name": (
            user.get("name")
            or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            or "Inconnu"
        ),
        "email": None,
        "company": user.get("company") or inferred_company,
        "job_title": user.get("job_title") or inferred_title,
        "bio": user.get("bio_short") or user.get("bio"),
        "avatar_url": user.get("avatar_url"),
        "linkedin_url": _build_linkedin(user.get("linkedin_handle")),
        "twitter_handle": _normalize_handle(user.get("twitter_handle")),
        "telegram_handle": _normalize_handle(user.get("telegram_handle")),
        "instagram_handle": _normalize_handle(user.get("instagram_handle")),
        "tiktok_handle": _normalize_handle(user.get("tiktok_handle")),
        "youtube_handle": _normalize_handle(user.get("youtube_handle")),
        "website": _normalize_handle(user.get("website")),
        "location": user.get("timezone"),
    }
