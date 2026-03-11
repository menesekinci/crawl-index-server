import respx
from httpx import Response

from app.config import Settings
from app.services.cloudflare import CloudflareCrawlClient


@respx.mock
def test_cloudflare_job_mapping():
    settings = Settings(cf_account_id="acc", cf_api_token="token")
    route = respx.get("https://api.cloudflare.com/client/v4/accounts/acc/browser-rendering/crawl/job-1").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "job-1",
                    "status": "completed",
                    "total": 1,
                    "finished": 1,
                    "skipped": 0,
                    "records": [
                        {
                            "url": "https://docs.example.com",
                            "status": "completed",
                            "markdown": "# Docs",
                            "metadata": {
                                "status": 200,
                                "title": "Docs Home",
                                "url": "https://docs.example.com",
                            },
                        }
                    ],
                },
            },
        )
    )

    result = CloudflareCrawlClient(settings).get_job("job-1")

    assert route.called
    assert result.status == "completed"
    assert result.records[0].title == "Docs Home"
    assert result.records[0].status_code == 200
    assert result.records[0].markdown == "# Docs"

