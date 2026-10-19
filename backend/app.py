"""SkyControl: hybrid AI-assisted air traffic management laboratory (FastAPI).

Start with:  python run.py   (or  uvicorn backend.app:app)
Educational simulation and analysis tool. Not operational ATC software.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, FRONTEND_DIR
from .database import connect
from .routes import airspace, auth_routes, data, insight, lab, operations
from .seed import seed


def _warm_analytics():
    """Build (or load) the cached real-data analysis in the background so startup stays fast."""
    try:
        from .analytics import pipeline
        pipeline.get(verbose=True)
    except Exception as exc:  # reported on /api/health, never fatal for the operations pages
        _state['analytics_error'] = str(exc)[:300]


_state = {}


@asynccontextmanager
async def lifespan(instance):
    seed()
    if os.getenv('SKYCONTROL_SKIP_WARMUP') != '1':
        threading.Thread(target=_warm_analytics, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan, title=f'{APP_NAME} hybrid ATM laboratory', version=APP_VERSION,
              description='Educational simulation and analysis. NOT operational air traffic control software.')
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.url.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH'):
        size = request.headers.get('content-length')
        if size and int(size) > 3_000_000:
            return JSONResponse({'error': 'Request too large'}, status_code=413)
    res = await call_next(request)
    res.headers['X-Content-Type-Options'] = 'nosniff'
    res.headers['X-Frame-Options'] = 'DENY'
    res.headers['Referrer-Policy'] = 'no-referrer'
    res.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
    res.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                              "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'")
    if os.getenv('SKYCONTROL_HTTPS') == '1':
        res.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return res


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse({'error': detail.get('message', 'Request failed'), 'details': detail}, status_code=exc.status_code)
    return JSONResponse({'error': detail}, status_code=exc.status_code)


@app.exception_handler(sqlite3.DatabaseError)
async def database_error(request, exc):
    return JSONResponse({'error': 'Database temporarily unavailable; no change was confirmed'}, status_code=503,
                        headers={'Retry-After': '5'})


@app.get('/api/health')
def health():
    with connect() as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
            raise HTTPException(503, 'Database schema not ready')
    from .analytics import pipeline
    return {'status': 'ok', 'application': APP_NAME, 'version': APP_VERSION, 'mode': 'RESEARCH_SIMULATION_ONLY',
            'analytics_ready': 'result' in pipeline._memory, 'analytics_error': _state.get('analytics_error')}


for module in (auth_routes, operations, lab, airspace, insight, data):
    app.include_router(module.router)

app.mount('/static', StaticFiles(directory=FRONTEND_DIR), name='static')


@app.get('/')
def index():
    return FileResponse(FRONTEND_DIR / 'index.html')
