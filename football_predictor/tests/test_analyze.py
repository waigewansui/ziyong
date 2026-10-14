"""
单元测试
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.analyze import poisson_probability, _normalize, _parse_score, calc_score
from modules.output import kelly_stake


def test_poisson():
    assert abs(poisson_probability(2.0, 0) - 0.1353) < 0.001
    assert abs(poisson_probability(2.0, 1) - 0.2707) < 0.001
    assert poisson_probability(1.0, 0) > 0.35  # λ=1 时 P(0球)≈0.3679
    assert poisson_probability(5.0, 0) < 0.01  # λ=5 时几乎不可能 0 球
    print("✓ test_poisson 通过")


def test_normalize():
    p = _normalize({"胜": 2, "平": 1, "负": 1})
    assert abs(p["胜"] - 0.5) < 0.001
    assert abs(sum(p.values()) - 1.0) < 0.001
    print("✓ test_normalize 通过")


def test_parse_score():
    assert _parse_score("2:1") == (2, 1)
    assert _parse_score("2-1") == (2, 1)
    assert _parse_score([3, 0]) == (3, 0)
    assert _parse_score(None) == (0, 0)
    print("✓ test_parse_score 通过")


def test_kelly_bounds():
    r = kelly_stake(0.70, 1.54, 1000)
    assert 0 <= r["stake_final"] <= 20, f"超限: {r}"
    r2 = kelly_stake(0.30, 2.00, 1000)
    assert r2["stake_final"] == 0, f"应该不投: {r2}"
    print("✓ test_kelly_bounds 通过")


def test_score_diversity():
    """不同输入产生不同 λ"""
    h1 = {"home_recent": [{"score": "3:0", "main_team": "team_A", "team_A_name": "A"}],
          "away_recent": [{"score": "0:2", "main_team": "team_A", "team_A_name": "B"}]}
    h2 = {"home_recent": [{"score": "1:1", "main_team": "team_A", "team_A_name": "A"}],
          "away_recent": [{"score": "1:1", "main_team": "team_A", "team_A_name": "B"}]}
    r1 = calc_score(h1, home="A", away="B", league="英超")
    r2 = calc_score(h2, home="A", away="B", league="英超")
    # 排除非比分 key
    r1_scores = {k: v for k, v in r1.items() if ":" in k}
    r2_scores = {k: v for k, v in r2.items() if ":" in k}
    top1 = max(r1_scores.items(), key=lambda x: x[1])[0]
    top2 = max(r2_scores.items(), key=lambda x: x[1])[0]
    assert top1 != top2, f"比分应不同: {top1} vs {top2}"
    print(f"✓ test_score_diversity 通过 ({top1} vs {top2})")


if __name__ == "__main__":
    test_poisson()
    test_normalize()
    test_parse_score()
    test_kelly_bounds()
    test_score_diversity()
    print("\n🎉 全部单元测试通过")
