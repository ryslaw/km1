import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="status-page")
templates = Jinja2Templates(directory="app/templates")

# Probe and scrape traffic is excluded to keep the metrics about real requests.
# The Ingress sends every unmatched path here (catch-all "/"), so /metrics is
# also reachable through it, like /health.
instrumentator = Instrumentator(excluded_handlers=["^/health$", "^/metrics$"])
instrumentator.instrument(app).expose(app, include_in_schema=False)

SERVICES = [
    ("user-service", os.getenv("USER_SERVICE_URL", "http://user-service:8000")),
    (
        "product-service",
        os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8000"),
    ),
    ("order-service", os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")),
]


async def check_health(client: httpx.AsyncClient, name: str, base_url: str) -> dict:
    """Query a single service's /health endpoint and summarize the result.

    Args:
        client: Shared httpx async client used for the request.
        name: Display name of the service being checked.
        base_url: Base URL of the service to query.

    Returns:
        dict: `{"name", "status": "up"|"down", "detail": ...}` describing
        the outcome; network/HTTP errors are caught and reported as "down"
        rather than propagated.
    """
    try:
        resp = await client.get(f"{base_url}/health", timeout=6.0)
        resp.raise_for_status()
        return {"name": name, "status": "up", "detail": resp.json().get("status", "ok")}
    except httpx.HTTPError as exc:
        return {
            "name": name,
            "status": "down",
            "detail": f"{type(exc).__name__}: {exc}",
        }


@app.get("/", response_class=HTMLResponse)
async def status_page(request: Request):
    """Render the dashboard showing the health of each downstream service.

    Args:
        request: Incoming HTTP request, required by Jinja2Templates.

    Returns:
        HTMLResponse: Rendered status.html page listing up/down state for
        user-service, product-service, and order-service.
    """
    async with httpx.AsyncClient() as client:
        results = [await check_health(client, name, url) for name, url in SERVICES]
    return templates.TemplateResponse(request, "status.html", {"services": results})


@app.get("/health")
def health():
    """Report status-page's own health for k8s readiness/liveness probes.

    Returns:
        dict: `{"status": "ok", "service": "status-page"}`.
    """
    return {"status": "ok", "service": "status-page"}
