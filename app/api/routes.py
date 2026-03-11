from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import DocumentResponse, HealthResponse, JobResponse, SearchRequest, SearchResult, SourceCreate

api_router = APIRouter(prefix="/api", tags=["api"])


def get_services(request: Request):
    return request.app.state.services


@api_router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        cloudflare_enabled=settings.cloudflare_enabled,
        embedding_model=settings.embedding_model,
    )


@api_router.get("/sources")
def list_sources(request: Request):
    return get_services(request).source_service.list_sources()


@api_router.post("/sources")
def create_source(payload: SourceCreate, request: Request):
    source = get_services(request).source_service.create_source(payload.model_dump())
    return source


@api_router.get("/sources/{source_id}")
def get_source(source_id: str, request: Request):
    source = get_services(request).source_service.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@api_router.post("/sources/{source_id}/crawl", response_model=JobResponse)
def crawl_source(source_id: str, request: Request):
    try:
        job = get_services(request).crawl_coordinator.create_and_submit_job(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobResponse.model_validate(job)


@api_router.post("/sources/{source_id}/reindex")
def reindex_source(source_id: str, request: Request):
    count = get_services(request).crawl_coordinator.reindex_source(source_id)
    return {"source_id": source_id, "reindexed_documents": count}


@api_router.get("/jobs")
def list_jobs(request: Request):
    return get_services(request).crawl_coordinator.list_jobs()


@api_router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request):
    job = get_services(request).crawl_coordinator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@api_router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str, request: Request):
    try:
        job = get_services(request).crawl_coordinator.retry_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobResponse.model_validate(job)


@api_router.get("/documents")
def list_documents(request: Request):
    return get_services(request).crawl_coordinator.list_documents()


@api_router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, request: Request):
    document = get_services(request).crawl_coordinator.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(document)


@api_router.post("/search", response_model=list[SearchResult])
def search(payload: SearchRequest, request: Request):
    results = get_services(request).search_service.search(payload.query, payload.limit, payload.source_id)
    return [SearchResult.model_validate(item) for item in results]

