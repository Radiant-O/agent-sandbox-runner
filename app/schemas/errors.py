"""Uniform error envelope."""

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None


class ErrorResponse(BaseModel):
    error: ErrorBody
