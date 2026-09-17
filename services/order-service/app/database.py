import os
import time

import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://order_service:order_service_pw@localhost:5434/order_service_db",
)

# In Kubernetes: http://user-service.microservices-lab.svc.cluster.local:8000
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8001")
# In Kubernetes: http://product-service.microservices-lab.svc.cluster.local:8000
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8002")

engine = create_engine(
    DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 2}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def wait_for_db(max_retries: int = 15, delay_seconds: float = 2.0) -> None:
    """Waits until the database starts accepting connections before the app proceeds.

    Args:
        max_retries: Maximum number of connection attempts before giving up.
        delay_seconds: Delay between attempts.

    Raises:
        RuntimeError: If the database is still unreachable after
        `max_retries` attempts.
    """
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            print(
                f"[order-service] database unavailable, attempt {attempt}/{max_retries}..."
            )
            time.sleep(delay_seconds)
    raise RuntimeError("Could not connect to the database after multiple attempts")


def is_db_alive() -> bool:
    """Lightweight database connectivity check – used by /health.
    Opens a raw psycopg2 connection (bypassing the SQLAlchemy pool) so that
    connect_timeout actually bounds the wait – a pooled connection could
    already be established but dead, and would not be subject to connect_timeout.

    Returns:
        bool: True if a new connection could be opened, False otherwise.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=2)
        conn.close()
        return True
    except psycopg2.OperationalError:
        return False


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session per request.

    Yields:
        Session: A session bound to the engine; closed automatically once
        the request is done, regardless of success or failure.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
