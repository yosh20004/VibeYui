from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("VibeYui-WebSearch")


def _serper_api_key() -> str:
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY 未设置。")
    return api_key


@mcp.tool()
def web_search(query: str, num_results: int = 5) -> str:
    """Use Serper.dev for web search and return compact JSON text."""
    clean_query = query.strip()
    if not clean_query:
        return json.dumps({"error": "query 不能为空"}, ensure_ascii=False)

    if num_results <= 0:
        num_results = 5
    if num_results > 10:
        num_results = 10

    payload = json.dumps({"q": clean_query, "num": num_results}).encode("utf-8")
    headers = {
        "X-API-KEY": _serper_api_key(),
        "Content-Type": "application/json",
    }

    request = Request(
        url="https://google.serper.dev/search",
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=15.0) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return json.dumps(
            {"error": f"serper http error {exc.code}", "detail": detail[:500]},
            ensure_ascii=False,
        )
    except URLError as exc:
        return json.dumps({"error": f"network error: {exc.reason}"}, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        return json.dumps({"error": f"unexpected error: {exc}"}, ensure_ascii=False)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    organic = parsed.get("organic")
    compact: list[dict[str, str]] = []
    if isinstance(organic, list):
        for item in organic[:num_results]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            link = item.get("link")
            snippet = item.get("snippet")
            compact.append(
                {
                    "title": title if isinstance(title, str) else "",
                    "link": link if isinstance(link, str) else "",
                    "snippet": snippet if isinstance(snippet, str) else "",
                }
            )

    return json.dumps(
        {
            "query": clean_query,
            "results": compact,
            "total_results": len(compact),
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
