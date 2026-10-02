"""Shared base class for all domain models."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Immutable, strict base model. Unknown fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")
