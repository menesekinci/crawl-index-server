from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.schemas import SearchRequest, SourceCreate

ui_router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory="app/ui/templates")


def _services(request: Request):
    return request.app.state.services


@ui_router.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/admin/sources", status_code=303)


@ui_router.get("/admin/sources", response_class=HTMLResponse)
def sources_page(request: Request):
    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "sources": _services(request).source_service.list_sources(),
            "cloudflare_enabled": request.app.state.settings.cloudflare_enabled,
        },
    )


@ui_router.post("/admin/sources", response_class=HTMLResponse)
def create_source_page(
    request: Request,
    name: str = Form(...),
    start_url: str = Form(...),
    allowed_domains: str = Form(""),
    source_type: str = Form("docs"),
    cron_expr: str = Form(""),
    enabled: bool = Form(False),
    crawl_depth: int = Form(1),
    crawl_limit: int = Form(50),
    render: bool = Form(False),
    formats: str = Form("markdown"),
):
    payload = SourceCreate(
        name=name,
        start_url=start_url,
        allowed_domains=[item.strip() for item in allowed_domains.split(",") if item.strip()],
        source_type=source_type,
        cron_expr=cron_expr or None,
        enabled=enabled,
        crawl_depth=crawl_depth,
        crawl_limit=crawl_limit,
        render=render,
        formats=[item.strip() for item in formats.split(",") if item.strip()],
    )
    _services(request).source_service.create_source(payload.model_dump())
    return RedirectResponse(url="/admin/sources", status_code=303)


@ui_router.get("/admin/sources/{source_id}", response_class=HTMLResponse)
def source_detail_page(source_id: str, request: Request):
    source = _services(request).source_service.get_source(source_id)
    jobs = [job for job in _services(request).crawl_coordinator.list_jobs() if job.source_id == source_id][:10]
    documents = [doc for doc in _services(request).crawl_coordinator.list_documents() if doc.source_id == source_id][:20]
    return templates.TemplateResponse(
        request,
        "source_detail.html",
        {
            "source": source,
            "jobs": jobs,
            "documents": documents,
            "cloudflare_enabled": request.app.state.settings.cloudflare_enabled,
        },
    )


@ui_router.post("/admin/sources/{source_id}/crawl")
def source_crawl_action(source_id: str, request: Request):
    _services(request).crawl_coordinator.create_and_submit_job(source_id)
    return RedirectResponse(url=f"/admin/sources/{source_id}", status_code=303)


@ui_router.post("/admin/sources/{source_id}/reindex")
def source_reindex_action(source_id: str, request: Request):
    _services(request).crawl_coordinator.reindex_source(source_id)
    return RedirectResponse(url=f"/admin/sources/{source_id}", status_code=303)


@ui_router.get("/admin/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {"jobs": _services(request).crawl_coordinator.list_jobs()},
    )


@ui_router.post("/admin/jobs/{job_id}/retry")
def retry_job_action(job_id: str, request: Request):
    _services(request).crawl_coordinator.retry_job(job_id)
    return RedirectResponse(url="/admin/jobs", status_code=303)


@ui_router.get("/admin/search", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse(
        request,
        "search.html",
        {"results": [], "sources": _services(request).source_service.list_sources()},
    )


@ui_router.post("/admin/search/results", response_class=HTMLResponse)
def search_results(
    request: Request,
    query: str = Form(...),
    limit: int = Form(10),
    source_id: str = Form(""),
):
    payload = SearchRequest(query=query, limit=limit, source_id=source_id or None)
    results = _services(request).search_service.search(payload.query, payload.limit, payload.source_id)
    return templates.TemplateResponse(
        request,
        "partials/search_results.html",
        {"results": results},
    )


@ui_router.get("/admin/documents/{document_id}", response_class=HTMLResponse)
def document_page(document_id: str, request: Request):
    document = _services(request).crawl_coordinator.get_document(document_id)
    return templates.TemplateResponse(
        request,
        "document_detail.html",
        {"document": document},
    )


@ui_router.get("/admin/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": request.app.state.settings},
    )


@ui_router.post("/admin/settings/cloudflare")
def update_cloudflare_settings(
    request: Request,
    cf_account_id: str = Form(""),
    cf_api_token: str = Form(""),
):
    import dotenv
    from app.config import get_settings
    
    dotenv.set_key(".env", "CF_ACCOUNT_ID", cf_account_id)
    dotenv.set_key(".env", "CF_API_TOKEN", cf_api_token)
    
    # Invalidate the cache to force a reload on the next request
    get_settings.cache_clear()
    
    # We update the current app state so changes are immediate
    request.app.state.settings = get_settings()
    
    return RedirectResponse(url="/admin/settings", status_code=303)

