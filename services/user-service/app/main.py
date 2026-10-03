import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import models
from .database import SessionLocal, engine, get_db, is_db_alive, wait_for_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    models.Base.metadata.create_all(bind=engine)
    yield


# Empty prefix locally (Docker Compose, service on its own port), but "/users"
# behind the k8s Ingress, which forwards paths without rewriting (see k8s/ingress/).
DOCS_PREFIX = os.getenv("DOCS_PREFIX", "")

app = FastAPI(
    title="user-service",
    docs_url=f"{DOCS_PREFIX}/docs",
    redoc_url=f"{DOCS_PREFIX}/redoc",
    openapi_url=f"{DOCS_PREFIX}/openapi.json",
    lifespan=lifespan,
)


# Manual chaos toggle for practicing k8s failure scenarios. "broken"
# (transient) lives in process memory: it fails both /health and /livez, so
# the liveness probe restarts the container, which resets it to False.
# "broken_permanent" lives in the database (ChaosState): it fails only
# /health, so the pod stays NotReady without a restart loop and survives pod
# restart/reschedule until an explicit /chaos/fix.
CHAOS_STATE = {"broken": False}


def _is_permanently_broken() -> bool:
    """Check whether the persistent chaos flag is set in the database.

    Returns:
        bool: True if the single ChaosState row (id=1) has broken=True,
        False if it is unset or the row does not exist yet.
    """
    db = SessionLocal()
    try:
        row = db.query(models.ChaosState).filter(models.ChaosState.id == 1).first()
        return bool(row.broken) if row else False
    finally:
        db.close()


def _set_permanently_broken(broken: bool) -> None:
    """Create or update the single ChaosState row with the given flag value.

    Args:
        broken: New value to persist for the permanent chaos flag.
    """
    db = SessionLocal()
    try:
        row = db.query(models.ChaosState).filter(models.ChaosState.id == 1).first()
        if row is None:
            db.add(models.ChaosState(id=1, broken=broken))
        else:
            row.broken = broken
        db.commit()
    finally:
        db.close()


async def _read_permanent_flag() -> bool:
    """Read the persistent chaos flag without blocking the event loop.

    The synchronous database query runs in Starlette's thread pool, the same
    one that serves plain `def` route handlers. If the database is
    unreachable, the flag is treated as unset ("fail open"): the request
    continues, and routes that need the database fail with 503 through
    `db_unavailable_handler` or, for `/health`, through its own error branch.

    Returns:
        bool: The persistent flag, or False if the database is unreachable.
    """
    try:
        return await run_in_threadpool(_is_permanently_broken)
    except OperationalError:
        print("[user-service] chaos flag unreadable, database unavailable")
        return False


@app.middleware("http")
async def chaos_middleware(request: Request, call_next):
    """Short-circuit requests with 503 while chaos mode is active.

    Requests to the chaos endpoints and to `/livez` are always passed
    through: the chaos endpoints must stay reachable to clear the flags,
    and `/livez` must answer without a database query.

    Args:
        request: Incoming HTTP request.
        call_next: Next handler in the middleware chain.

    Returns:
        A 503 JSONResponse if the service is marked broken (transient or
        permanent), otherwise the downstream response.
    """
    if request.url.path.startswith(f"{DOCS_PREFIX}/chaos"):
        return await call_next(request)
    if request.url.path == "/livez":
        return await call_next(request)
    if CHAOS_STATE["broken"] or await _read_permanent_flag():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "user-service intentionally broken (chaos toggle) — "
                "POST /chaos/fix to restore"
            },
        )
    return await call_next(request)


@app.post(f"{DOCS_PREFIX}/chaos/break")
def chaos_break():
    """Set the transient chaos flag.

    The flag lives in process memory, so it clears itself on container
    restart (e.g. via a liveness probe).
    """
    CHAOS_STATE["broken"] = True
    return {"broken": True, "broken_permanent": _is_permanently_broken()}


@app.post(f"{DOCS_PREFIX}/chaos/break-permanent")
def chaos_break_permanent():
    """Set the persistent chaos flag.

    The flag is stored in the database, so it survives pod restart and
    reschedule until an explicit /chaos/fix.
    """
    _set_permanently_broken(True)
    return {"broken": True, "broken_permanent": True}


@app.post(f"{DOCS_PREFIX}/chaos/fix")
def chaos_fix():
    """Clear both chaos flags at once — transient and persistent."""
    CHAOS_STATE["broken"] = False
    _set_permanently_broken(False)
    return {"broken": False, "broken_permanent": False}


@app.get(f"{DOCS_PREFIX}/chaos/status")
def chaos_status():
    """Report the current chaos state.

    Returns:
        dict: Combined `broken` flag plus the individual `broken_transient`
        and `broken_permanent` flags.
    """
    permanent = _is_permanently_broken()
    return {
        "broken": CHAOS_STATE["broken"] or permanent,
        "broken_transient": CHAOS_STATE["broken"],
        "broken_permanent": permanent,
    }


@app.exception_handler(OperationalError)
async def db_unavailable_handler(request: Request, exc: OperationalError):
    """Convert unhandled SQLAlchemy connection errors into a 503 response.

    Args:
        request: Incoming HTTP request that triggered the error.
        exc: The OperationalError raised while accessing the database.

    Returns:
        JSONResponse: 503 with a generic "Database unavailable" detail.
    """
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health")
def health():
    """Report service health for the k8s readiness probe.

    Returns:
        dict: `{"status": "ok", "service": "user-service"}` when the
        database is reachable; otherwise a 503 JSONResponse with
        `{"status": "error", ...}`.
    """
    if not is_db_alive():
        return JSONResponse(
            status_code=503, content={"status": "error", "service": "user-service"}
        )
    return {"status": "ok", "service": "user-service"}


@app.get("/livez")
async def livez():
    """Report process liveness for the k8s liveness probe.

    Reads in-memory state only and never touches the database, so a
    database outage or the persistent chaos flag cannot trigger a restart.
    Declared `async` so it is answered by the event loop itself instead of
    queueing in the thread pool behind handlers blocked on the database.

    Returns:
        dict: `{"status": "ok", "service": "user-service"}` normally;
        a 503 JSONResponse with `{"status": "error", ...}` while the
        transient chaos flag is set, which a container restart clears.
    """
    if CHAOS_STATE["broken"]:
        return JSONResponse(
            status_code=503, content={"status": "error", "service": "user-service"}
        )
    return {"status": "ok", "service": "user-service"}


@app.post("/users", response_model=models.UserOut, status_code=201)
def create_user(payload: models.UserCreate, db: Session = Depends(get_db)):
    """Register a new user.

    Args:
        payload: New user's email and full name.
        db: SQLAlchemy session injected via FastAPI dependency.

    Returns:
        models.User: The newly created user row.

    Raises:
        HTTPException: 409 if the email is already registered.
    """
    user = models.User(email=payload.email, full_name=payload.full_name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    db.refresh(user)
    return user


@app.get("/users/{user_id}", response_model=models.UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Fetch a single user by id.

    Args:
        user_id: Primary key of the user to look up.
        db: SQLAlchemy session injected via FastAPI dependency.

    Returns:
        models.User: The matching user.

    Raises:
        HTTPException: 404 if no user with that id exists.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/users", response_model=list[models.UserOut])
def list_users(db: Session = Depends(get_db)):
    """List all registered users.

    Args:
        db: SQLAlchemy session injected via FastAPI dependency.

    Returns:
        list[models.User]: All users currently in the database.
    """
    return db.query(models.User).all()
