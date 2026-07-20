"""Westgard 멀티룰 판정 엔진 (순수 파이썬).

연구계획서 4.2 및 [표 1]의 규칙을 구현한다.

  1_2s : 1개 값이 ±2SD 초과            → 경고(warning), 추가 규칙 검토
  1_3s : 1개 값이 ±3SD 초과            → 거부, 무작위오차
  2_2s : 연속 2개가 동일 방향 ±2SD 초과 → 거부, 계통오차
  R_4s : 동일 런/인접 두 값의 범위 4SD 초과 → 거부, 무작위오차
  4_1s : 연속 4개가 동일 방향 ±1SD 초과 → 거부, 계통오차
  10x  : 연속 10개가 평균 한쪽에 위치   → 거부, 계통오차
  8x   : 연속 8개가 평균 한쪽에 위치     → 거부, 계통오차 (옵션)
  7T   : 연속 7개가 상승/하강 추세       → 거부, 계통오차 (옵션)

각 규칙은 "가장 최근 값(마지막 원소)"을 기준으로 위반 여부를 판정한다.
z-score 계열(z[0..n], 마지막이 최신)을 입력받는다.
"""
from dataclasses import dataclass, field
from typing import List, Dict


# 규칙 메타데이터 (판정문/오차유형/심각도)
RULE_INFO = {
    "1_2s": ("1개 값이 ±2SD 초과", "경고", "warning"),
    "1_3s": ("1개 값이 ±3SD 초과", "무작위오차", "reject"),
    "2_2s": ("연속 2개가 동일 방향 ±2SD 초과", "계통오차", "reject"),
    "R_4s": ("인접 두 값의 범위가 4SD 초과", "무작위오차", "reject"),
    "4_1s": ("연속 4개가 동일 방향 ±1SD 초과", "계통오차", "reject"),
    "10x": ("연속 10개가 평균 한쪽에 위치", "계통오차", "reject"),
    "8x": ("연속 8개가 평균 한쪽에 위치", "계통오차", "reject"),
    "7T": ("연속 7개가 상승/하강 추세", "계통오차", "reject"),
}

# 적용 규칙 집합.
# 검사실 정책에 따라 10ₓ(연속 10개 평균 한쪽) 규칙은 적용하지 않는다.
# (배정평균 대비 소편의에 과민 반응하여 위양성 위반을 유발하므로 제외)
# 8ₓ·7T 도 기본 적용에서 제외한다. 필요 시 evaluate_point(rules=[...]) 로 개별 지정 가능.
DEFAULT_RULES = ["1_2s", "1_3s", "2_2s", "R_4s", "4_1s"]

# 참고: 엔진은 10ₓ·8ₓ·7T 판정 로직을 모두 보유하며, 아래 집합으로 확장 적용할 수 있다.
ALL_RULES = ["1_2s", "1_3s", "2_2s", "R_4s", "4_1s", "10x", "8x", "7T"]


@dataclass
class Evaluation:
    z: float
    violated: List[str] = field(default_factory=list)   # 위반 규칙 코드
    status: str = "accept"                               # accept / warning / reject

    @property
    def is_reject(self):
        return self.status == "reject"


def _same_side_over(seq, threshold):
    """seq 전부가 동일 방향으로 threshold(부호 포함 절대값) 초과인지."""
    if all(v > threshold for v in seq):
        return True
    if all(v < -threshold for v in seq):
        return True
    return False


def _same_side_mean(seq):
    """seq 전부가 평균 한쪽(모두 >0 또는 모두 <0)인지."""
    return all(v > 0 for v in seq) or all(v < 0 for v in seq)


def evaluate_point(z_history: List[float], rules: List[str] = None) -> Evaluation:
    """z_history 의 마지막 값에 대해 멀티룰을 적용한다.

    z_history: 시간순 z-score 리스트 (마지막이 최신 값)
    """
    if rules is None:
        rules = DEFAULT_RULES
    if not z_history:
        return Evaluation(z=0.0)

    z = z_history[-1]
    ev = Evaluation(z=z)
    n = len(z_history)

    # 1_3s
    if "1_3s" in rules and abs(z) > 3:
        ev.violated.append("1_3s")

    # 1_2s (경고 트리거)
    if "1_2s" in rules and abs(z) > 2:
        ev.violated.append("1_2s")

    # 2_2s : 최근 2개가 동일 방향 ±2SD 초과
    if "2_2s" in rules and n >= 2:
        if _same_side_over(z_history[-2:], 2):
            ev.violated.append("2_2s")

    # R_4s : 인접 두 값의 차가 4SD 초과 (한 값 +2SD 초과, 다른 값 -2SD 초과 포함)
    if "R_4s" in rules and n >= 2:
        if abs(z_history[-1] - z_history[-2]) > 4:
            ev.violated.append("R_4s")

    # 4_1s : 최근 4개가 동일 방향 ±1SD 초과
    if "4_1s" in rules and n >= 4:
        if _same_side_over(z_history[-4:], 1):
            ev.violated.append("4_1s")

    # 10x : 최근 10개가 평균 한쪽
    if "10x" in rules and n >= 10:
        if _same_side_mean(z_history[-10:]):
            ev.violated.append("10x")

    # 8x
    if "8x" in rules and n >= 8:
        if _same_side_mean(z_history[-8:]):
            if "8x" not in ev.violated:
                ev.violated.append("8x")

    # 7T : 최근 7개가 단조 증가 또는 단조 감소
    if "7T" in rules and n >= 7:
        seg = z_history[-7:]
        inc = all(seg[i] < seg[i + 1] for i in range(len(seg) - 1))
        dec = all(seg[i] > seg[i + 1] for i in range(len(seg) - 1))
        if inc or dec:
            ev.violated.append("7T")

    # 상태 결정: reject 규칙이 하나라도 있으면 reject, 없고 1_2s만 있으면 warning
    reject_rules = [r for r in ev.violated if RULE_INFO[r][2] == "reject"]
    if reject_rules:
        ev.status = "reject"
    elif "1_2s" in ev.violated:
        ev.status = "warning"
    else:
        ev.status = "accept"
    return ev


def evaluate_series(z_history: List[float], rules: List[str] = None) -> List[Evaluation]:
    """전체 시계열을 순차 평가하여 각 시점의 Evaluation 리스트를 반환."""
    out = []
    for i in range(len(z_history)):
        out.append(evaluate_point(z_history[: i + 1], rules))
    return out


def z_of(value: float, mean: float, sd: float) -> float:
    if not sd:
        return 0.0
    return (value - mean) / sd


def summarize(evals: List[Evaluation]) -> Dict[str, int]:
    """시계열 판정 요약 (규칙별 위반 건수)."""
    counts = {"accept": 0, "warning": 0, "reject": 0}
    rule_counts = {}
    for e in evals:
        counts[e.status] += 1
        for r in e.violated:
            rule_counts[r] = rule_counts.get(r, 0) + 1
    return {"status_counts": counts, "rule_counts": rule_counts}
