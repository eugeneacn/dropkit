"""Async Confluence REST client for both Cloud and Server/Data Center.

Internal module — agent should not invoke directly. The API token is read
from the environment only; it is never logged, echoed, or placed on the
command line.

Auth selection:
- Cloud  (host matches *.atlassian.net): HTTP Basic with email:api_token
- Server/DC (anything else):             Bearer <Personal Access Token>

Override auto-detection by setting CONFLUENCE_FLAVOR=cloud|server.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

log = logging.getLogger("confluence_crawler.client")

DEFAULT_CONCURRENCY = 4
DEFAULT_MIN_DELAY_MS = 100
DEFAULT_TIMEOUT_S = 30.0
MAX_RETRIES = 5
PAGE_SIZE = 50

FLAVOR_CLOUD = "cloud"
FLAVOR_SERVER = "server"


class ConfluenceError(Exception):
    pass


class AuthError(ConfluenceError):
    pass


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    version: int
    updated: str
    author: str | None
    parent_id: str | None
    labels: tuple[str, ...]
    storage_xhtml: str
    webui_path: str
    space_key: str


@dataclass(frozen=True)
class Attachment:
    id: str
    filename: str
    media_type: str
    download_path: str
    file_size: int


@dataclass(frozen=True)
class Credentials:
    base_url: str
    token: str
    flavor: str  # "cloud" or "server"
    email: str | None  # required when flavor == "cloud"


def detect_flavor(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    return FLAVOR_CLOUD if host.endswith(".atlassian.net") else FLAVOR_SERVER


class ConfluenceClient:
    """Async wrapper around the Confluence v1 REST API (works for both
    Cloud and Server/Data Center)."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        min_delay_ms: int = DEFAULT_MIN_DELAY_MS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        verify_tls: bool = True,
    ) -> None:
        base_url = credentials.base_url
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")

        self._base = base_url.rstrip("/")
        self._flavor = credentials.flavor
        headers = {
            "Accept": "application/json",
            "User-Agent": "dropkit-confluence-crawler/1.0",
        }
        auth: httpx.Auth | None = None
        if credentials.flavor == FLAVOR_CLOUD:
            if not credentials.email:
                raise AuthError("Cloud auth requires CONFLUENCE_EMAIL")
            auth = httpx.BasicAuth(credentials.email, credentials.token)
        else:
            headers["Authorization"] = f"Bearer {credentials.token}"

        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers=headers,
            auth=auth,
            timeout=timeout_s,
            verify=verify_tls,
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._min_delay = min_delay_ms / 1000.0
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "ConfluenceClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async with self._sem:
            async with self._lock:
                now = asyncio.get_running_loop().time()
                wait = self._min_delay - (now - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = asyncio.get_running_loop().time()

            last_exc: Exception | None = None
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await self._client.request(method, path, **kwargs)
                except httpx.TransportError as exc:
                    last_exc = exc
                    await asyncio.sleep(self._backoff(attempt))
                    continue

                if resp.status_code == 401:
                    raise AuthError(
                        "401 Unauthorized — credentials are missing, invalid, or expired. "
                        "Re-run scripts/setup_credentials.sh."
                    )
                if resp.status_code == 403:
                    raise AuthError(
                        f"403 Forbidden for {path} — token lacks permission for this resource."
                    )
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else self._backoff(attempt)
                    log.warning("HTTP %s on %s — retrying in %.1fs", resp.status_code, path, delay)
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    raise ConfluenceError(f"HTTP {resp.status_code} on {path}: {resp.text[:300]}")
                return resp

            raise ConfluenceError(
                f"Exhausted {MAX_RETRIES} retries for {path}"
                + (f" (last error: {last_exc})" if last_exc else "")
            )

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, (2 ** attempt) * 0.5 + random.uniform(0, 0.5))

    # --- High-level operations ---

    async def whoami(self) -> dict:
        resp = await self._request("GET", "/rest/api/user/current")
        return resp.json()

    async def get_space_homepage_id(self, space_key: str) -> str | None:
        resp = await self._request(
            "GET",
            f"/rest/api/space/{space_key}",
            params={"expand": "homepage"},
        )
        data = resp.json()
        home = data.get("homepage") or {}
        hid = home.get("id")
        return str(hid) if hid else None

    async def get_page(self, page_id: str) -> Page:
        resp = await self._request(
            "GET",
            f"/rest/api/content/{page_id}",
            params={
                "expand": (
                    "body.storage,version,ancestors,space,"
                    "metadata.labels,history.createdBy,history.lastUpdated"
                )
            },
        )
        d = resp.json()
        ancestors = d.get("ancestors") or []
        parent_id = str(ancestors[-1]["id"]) if ancestors else None
        labels = tuple(
            lbl.get("name", "")
            for lbl in (d.get("metadata", {}).get("labels", {}).get("results") or [])
            if lbl.get("name")
        )
        history = d.get("history") or {}
        last_updated = (history.get("lastUpdated") or {}).get("when") or ""
        created_by = history.get("createdBy") or {}
        # username exists on Server/DC; Cloud only returns displayName/accountId.
        author = (
            created_by.get("username")
            or created_by.get("displayName")
            or created_by.get("publicName")
            or None
        )
        webui = ((d.get("_links") or {}).get("webui")) or ""
        return Page(
            id=str(d["id"]),
            title=d.get("title", ""),
            version=int((d.get("version") or {}).get("number", 1)),
            updated=last_updated,
            author=author,
            parent_id=parent_id,
            labels=labels,
            storage_xhtml=((d.get("body", {}).get("storage", {}) or {}).get("value") or ""),
            webui_path=webui,
            space_key=((d.get("space") or {}).get("key") or ""),
        )

    async def iter_children(self, page_id: str) -> AsyncIterator[dict]:
        start = 0
        while True:
            resp = await self._request(
                "GET",
                f"/rest/api/content/{page_id}/child/page",
                params={"start": start, "limit": PAGE_SIZE, "expand": "version"},
            )
            data = resp.json()
            for item in data.get("results", []):
                yield item
            size = int(data.get("size", 0))
            if size < PAGE_SIZE:
                return
            start += size

    async def iter_attachments(self, page_id: str) -> AsyncIterator[Attachment]:
        start = 0
        while True:
            resp = await self._request(
                "GET",
                f"/rest/api/content/{page_id}/child/attachment",
                params={"start": start, "limit": PAGE_SIZE},
            )
            data = resp.json()
            for item in data.get("results", []):
                ext = item.get("extensions") or {}
                links = item.get("_links") or {}
                yield Attachment(
                    id=str(item["id"]),
                    filename=item.get("title", str(item["id"])),
                    media_type=ext.get("mediaType", "application/octet-stream"),
                    download_path=links.get("download", ""),
                    file_size=int(ext.get("fileSize", 0) or 0),
                )
            size = int(data.get("size", 0))
            if size < PAGE_SIZE:
                return
            start += size

    async def download_attachment(self, download_path: str, dest: Path) -> None:
        if not download_path:
            raise ConfluenceError("attachment has no download path")
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._sem:
            async with self._client.stream("GET", download_path) as resp:
                if resp.status_code >= 400:
                    raise ConfluenceError(
                        f"HTTP {resp.status_code} downloading {download_path}"
                    )
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as fh:
                    async for chunk in resp.aiter_bytes():
                        fh.write(chunk)
                tmp.replace(dest)


def load_credentials() -> Credentials:
    """Read base URL, token, flavor, and (if cloud) email from the config
    file or environment.

    Precedence: explicit env vars > config file. Secrets are never returned
    through logging or exceptions other than an AuthError if missing.

    Recognized env vars:
      CONFLUENCE_BASE_URL   Base URL. For Cloud include /wiki (setup auto-adds).
      CONFLUENCE_API_TOKEN  API token (Cloud) or Personal Access Token (Server).
      CONFLUENCE_EMAIL      Atlassian account email (Cloud only).
      CONFLUENCE_FLAVOR     Optional: "cloud" or "server" to override detection.
    """
    values: dict[str, str | None] = {
        "CONFLUENCE_BASE_URL": os.environ.get("CONFLUENCE_BASE_URL"),
        "CONFLUENCE_API_TOKEN": os.environ.get("CONFLUENCE_API_TOKEN"),
        "CONFLUENCE_EMAIL": os.environ.get("CONFLUENCE_EMAIL"),
        "CONFLUENCE_FLAVOR": os.environ.get("CONFLUENCE_FLAVOR"),
    }

    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    # Prefer the shared dropkit credential file; fall back to the legacy
    # per-skill path so existing installs keep working.
    candidate_files = [
        config_dir / "dropkit" / "credentials.env",
        config_dir / "confluence-crawler" / "config.env",
    ]
    for config_file in candidate_files:
        if not config_file.is_file():
            continue
        try:
            from dotenv import dotenv_values
        except ImportError as exc:
            raise AuthError(
                "python-dotenv is required to read the config file; "
                "install requirements.txt first."
            ) from exc
        file_values = dotenv_values(config_file)
        for key in values:
            if not values[key]:
                values[key] = file_values.get(key)

    base = (values["CONFLUENCE_BASE_URL"] or "").rstrip("/")
    token = values["CONFLUENCE_API_TOKEN"] or ""
    if not base or not token:
        raise AuthError(
            "Missing credentials. Run scripts/setup_credentials.sh or set "
            "CONFLUENCE_BASE_URL and CONFLUENCE_API_TOKEN environment variables."
        )

    flavor = (values["CONFLUENCE_FLAVOR"] or "").strip().lower() or detect_flavor(base)
    if flavor not in (FLAVOR_CLOUD, FLAVOR_SERVER):
        raise AuthError(f"unsupported CONFLUENCE_FLAVOR: {flavor!r}")

    email = values["CONFLUENCE_EMAIL"] or None
    if flavor == FLAVOR_CLOUD and not email:
        raise AuthError(
            "Cloud authentication requires CONFLUENCE_EMAIL. Re-run "
            "scripts/setup_credentials.sh."
        )

    return Credentials(base_url=base, token=token, flavor=flavor, email=email)
