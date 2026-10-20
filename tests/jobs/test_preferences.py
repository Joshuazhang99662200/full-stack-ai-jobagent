from jobagent.jobs.preferences import preference_score
from jobagent.schemas.job_intelligence import PreferenceFactor

FACTORS = [
    PreferenceFactor(name="金融投研", terms=["投研", "证券"], weight=2),
    PreferenceFactor(name="评测", terms=["评测", "Eval"]),
    PreferenceFactor(name="原型", terms=["Demo", "原型"]),
]


def test_score_is_the_weighted_share_of_factors_the_posting_names() -> None:
    score, hits = preference_score("负责证券投研 Agent, 建设 eval 体系", FACTORS)

    assert hits == ["金融投研", "评测"]
    assert score == 0.75


def test_no_factors_means_no_preference() -> None:
    assert preference_score("anything", []) == (0.0, [])
