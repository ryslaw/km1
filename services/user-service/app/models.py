from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from .database import Base


class User(Base):
    """ORM model for a registered user."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChaosState(Base):
    """Single row (id=1) holding the persistent-failure flag — kept in the
    database, so it survives pod restart/reschedule unlike in-process state."""

    __tablename__ = "chaos_state"

    id = Column(Integer, primary_key=True)
    broken = Column(Boolean, nullable=False, default=False)


class UserCreate(BaseModel):
    """Request body for POST /users."""

    email: EmailStr
    full_name: str


class UserOut(BaseModel):
    """Response schema for user endpoints, mirroring the User ORM model."""

    id: int
    email: EmailStr
    full_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
