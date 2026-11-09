from app.core.security import RateLimiter, owner_id


def test_owner_id_is_stable_and_not_the_key() -> None:
    assert owner_id("secret") == owner_id("secret")
    assert owner_id("secret") != owner_id("other")
    assert len(owner_id("secret")) == 16
    assert "secret" not in owner_id("secret")


def test_rate_limiter_refills() -> None:
    now = [0.0]
    rl = RateLimiter(per_minute=2, clock=lambda: now[0])
    assert rl.check("k") is None
    assert rl.check("k") is None
    wait = rl.check("k")
    assert wait is not None and 0 < wait <= 30
    assert rl.check("other") is None  # buckets are per key
    now[0] += 30
    assert rl.check("k") is None
