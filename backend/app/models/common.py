"""Shared Pydantic helpers for working with MongoDB ObjectIds."""
from __future__ import annotations

from typing import Annotated, Any

from bson import ObjectId
from pydantic import BeforeValidator

# Represent Mongo ObjectId as a string everywhere in the API layer.
PyObjectId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]


def to_object_id(value: str | ObjectId) -> ObjectId:
    """Coerce a string id into an ObjectId, raising a clear error otherwise."""
    if isinstance(value, ObjectId):
        return value
    if ObjectId.is_valid(value):
        return ObjectId(value)
    raise ValueError(f"Invalid ObjectId: {value!r}")


def serialize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert a Mongo document's ``_id`` into a string ``id`` field."""
    if doc is None:
        return None
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
