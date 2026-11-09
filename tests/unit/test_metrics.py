from app.core.metrics import Metrics
from app.domain import ExecutionStatus


def test_snapshot_percentiles() -> None:
    m = Metrics()
    for ms in range(1, 101):
        m.execution_finished(ExecutionStatus.SUCCEEDED, ms)
    m.execution_finished(ExecutionStatus.FAILED, 5)
    m.sandbox_created(200)
    m.sandbox_created(400)
    m.sandbox_killed()
    m.cleanup_failed()
    m.create_retried()
    m.agent_run_finished("completed")
    s = m.snapshot()
    assert s["executions_by_status"] == {"succeeded": 100, "failed": 1}
    assert s["execution_duration_ms_p50"] == 50
    assert s["execution_duration_ms_p95"] == 95
    assert s["sandboxes_created_total"] == 2
    assert s["sandboxes_live"] == 0  # 2 created - 1 killed - 1 kill failed
    assert s["sandbox_create_ms_avg"] == 300
    assert s["cleanup_failures_total"] == 1
    assert s["create_retries_total"] == 1
    assert s["agent_runs_by_stop_reason"] == {"completed": 1}


def test_empty_snapshot() -> None:
    s = Metrics().snapshot()
    assert s["execution_duration_ms_p50"] is None
    assert s["sandbox_create_ms_avg"] is None
