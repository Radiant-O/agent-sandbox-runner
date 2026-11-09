import hashlib

import pytest
from pydantic import ValidationError

from app.domain import ExecutionRecord, ExecutionStatus
from app.schemas.executions import ExecutionCreate, ExecutionOut


def test_new_record_defaults() -> None:
    rec = ExecutionRecord.new("print(1)", 30, owner="o1")
    assert rec.id.startswith("exe_")
    assert rec.status is ExecutionStatus.QUEUED
    assert rec.code_sha256 == hashlib.sha256(b"print(1)").hexdigest()
    assert rec.code_size == len(b"print(1)")
    assert rec.source == "api"
    assert rec.created_at.tzinfo is not None
    assert rec.stdout == "" and rec.exit_code is None


def test_blank_code_rejected() -> None:
    with pytest.raises(ValidationError):
        ExecutionCreate(code="   ")


def test_execution_out_hides_code_and_owner() -> None:
    rec = ExecutionRecord.new("print(1)", 30, owner="o1")
    out = ExecutionOut.from_record(rec).model_dump()
    assert "code" not in out and "owner" not in out
    assert out["id"] == rec.id
    assert out["status"] == "queued"
