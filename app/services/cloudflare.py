from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings


class CloudflareNotConfiguredError(RuntimeError):
    pass


@dataclass
class CrawlRecord:
    url: str
    status: str
    title: str | None
    status_code: int | None
    markdown: str
    metadata: dict[str, Any]


@dataclass
class CrawlJobResult:
    id: str
    status: str
    total: int
    finished: int
    skipped: int
    records: list[CrawlRecord]


class CloudflareCrawlClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        if not self._settings.cloudflare_enabled:
            raise CloudflareNotConfiguredError("Cloudflare credentials are missing.")
        return {
            "Authorization": f"Bearer {self._settings.cf_api_token}",
            "Content-Type": "application/json",
        }

    @property
    def enabled(self) -> bool:
        return self._settings.cloudflare_enabled

    def submit_crawl(
        self,
        *,
        url: str,
        depth: int,
        limit: int,
        render: bool,
        formats: list[str],
    ) -> str:
        endpoint = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self._settings.cf_account_id}/browser-rendering/crawl"
        )
        payload = {
            "url": url,
            "depth": depth,
            "limit": limit,
            "render": render,
            "formats": formats,
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
        if not data.get("success"):
            raise RuntimeError(str(data.get("errors") or data))
        return str(data["result"])

    def get_job(self, provider_job_id: str) -> CrawlJobResult:
        endpoint = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self._settings.cf_account_id}/browser-rendering/crawl/{provider_job_id}"
        )
        all_records: list[CrawlRecord] = []
        total = 0
        finished = 0
        skipped = 0
        status = "unknown"
        job_id = ""
        cursor: str | None = None

        with httpx.Client(timeout=30.0) as client:
            while True:
                params: dict[str, str] = {}
                if cursor:
                    params["cursor"] = cursor
                response = client.get(endpoint, headers=self._headers(), params=params)
                response.raise_for_status()
                data = response.json()
                if not data.get("success"):
                    raise RuntimeError(str(data.get("errors") or data))
                result = data["result"]
                job_id = result["id"]
                status = result.get("status", "unknown")
                total = result.get("total", 0)
                finished = result.get("finished", 0)
                skipped += result.get("skipped", 0)
                for record in result.get("records", []):
                    metadata = record.get("metadata") or {}
                    all_records.append(
                        CrawlRecord(
                            url=record.get("url", ""),
                            status=record.get("status", ""),
                            title=metadata.get("title"),
                            status_code=metadata.get("status"),
                            markdown=record.get("markdown") or record.get("html") or record.get("json") or "",
                            metadata=metadata,
                        )
                    )
                cursor = result.get("cursor")
                if not cursor:
                    break
        return CrawlJobResult(
            id=job_id,
            status=status,
            total=total,
            finished=finished,
            skipped=skipped,
            records=all_records,
        )

