import asyncio
from typing import Optional
from duckduckgo_search import DDGS


async def _ddg_search(query: str, max_results: int = 3) -> list[dict]:
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(
            None,
            lambda: list(DDGS().text(query, max_results=max_results))
        )
        return results
    except Exception:
        return []


async def enrich_participant(
    name: str,
    company: Optional[str],
    job_title: Optional[str],
    existing_linkedin: Optional[str] = None,
) -> dict:
    """
    Enriches a participant with public info from DuckDuckGo.
    Returns a dict of fields to update.
    """
    updates: dict = {}
    await asyncio.sleep(1.5)  # polite rate limit

    # --- Company description ---
    if company:
        query = f'"{company}" fintech blockchain finance services'
        results = await _ddg_search(query, max_results=3)
        for r in results:
            body = r.get("body", "")
            if len(body) > 80:
                updates["company_description"] = body[:600]
                break

    # --- LinkedIn URL (if not already known) ---
    if not existing_linkedin and name:
        context = " ".join(filter(None, [company, job_title]))
        query = f'site:linkedin.com/in "{name}" {context}'
        results = await _ddg_search(query, max_results=5)
        for r in results:
            url = r.get("href", "")
            if "linkedin.com/in/" in url:
                updates["linkedin_url"] = url.split("?")[0]
                break

    # --- If still no company description, try person-centric search ---
    if "company_description" not in updates and name and company:
        query = f'"{name}" "{company}" blockchain crypto finance'
        results = await _ddg_search(query, max_results=3)
        for r in results:
            body = r.get("body", "")
            if len(body) > 60:
                updates["company_description"] = body[:400]
                break

    return updates
