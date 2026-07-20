"""Westgard 멀티룰 엔진 단위테스트.

    python -m pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.westgard import evaluate_point, evaluate_series, z_of  # noqa: E402


def test_accept_within_2sd():
    ev = evaluate_point([0.5, -0.3, 1.1, -1.5])
    assert ev.status == "accept"
    assert ev.violated == []


def test_1_2s_warning():
    ev = evaluate_point([0.2, 2.5])
    assert "1_2s" in ev.violated
    assert ev.status == "warning"          # 1_2s 단독은 경고


def test_1_3s_reject():
    ev = evaluate_point([0.1, 3.4])
    assert "1_3s" in ev.violated
    assert ev.status == "reject"


def test_2_2s_same_side_reject():
    ev = evaluate_point([0.1, 2.3, 2.6])
    assert "2_2s" in ev.violated
    assert ev.status == "reject"


def test_2_2s_opposite_side_not_triggered():
    ev = evaluate_point([0.1, 2.3, -2.6])
    assert "2_2s" not in ev.violated


def test_R_4s_reject():
    ev = evaluate_point([0.0, 2.2, -2.1])   # 범위 4.3SD > 4SD
    assert "R_4s" in ev.violated
    assert ev.status == "reject"


def test_4_1s_same_side_reject():
    ev = evaluate_point([1.2, 1.4, 1.1, 1.6])
    assert "4_1s" in ev.violated
    assert ev.status == "reject"


def test_4_1s_needs_four_points():
    ev = evaluate_point([1.2, 1.4, 1.1])    # 3개뿐
    assert "4_1s" not in ev.violated


def test_10x_not_applied_by_default():
    # 검사실 정책상 10ₓ 는 기본 적용 규칙에서 제외됨
    ev = evaluate_point([0.2] * 10)
    assert "10x" not in ev.violated
    assert ev.status == "accept"


def test_10x_available_when_explicitly_enabled():
    # 엔진은 10ₓ 로직을 보유 — 명시적으로 지정하면 판정 가능
    ev = evaluate_point([0.2] * 10, rules=["1_2s", "1_3s", "10x"])
    assert "10x" in ev.violated
    assert ev.status == "reject"


def test_7T_trend_reject():
    ev = evaluate_point([-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6], rules=[
        "1_2s", "1_3s", "2_2s", "R_4s", "4_1s", "10x", "7T"])
    assert "7T" in ev.violated


def test_z_of():
    assert round(z_of(58.0, 57.4, 1.72), 2) == 0.35
    assert z_of(10, 10, 0) == 0.0


def test_series_length():
    zs = [0.1, 0.2, 2.5, 3.4]
    evals = evaluate_series(zs)
    assert len(evals) == 4
    assert evals[-1].status == "reject"      # 마지막 3.4 → 1_3s
