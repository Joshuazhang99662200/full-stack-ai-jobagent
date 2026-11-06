"""Monte Carlo check of the effect verdicts on synthetic outcomes with a known truth.

Answers: with no real lift, how often would we claim one; with a real lift, how
often do we detect it at a given sample size. Seeded and deterministic.
"""

import random

from jobagent.errors import ContractValidationError
from jobagent.memory.effect import compare_rates
from jobagent.schemas.memory import SimulationResult


def simulate(
    *,
    trials: int,
    sample_size: int,
    base_rate: float,
    lift: float,
    min_sample: int,
    seed: int,
) -> SimulationResult:
    treated_rate = base_rate + lift
    if trials < 1 or sample_size < 1 or not 0 <= base_rate <= 1 or not 0 <= treated_rate <= 1:
        raise ContractValidationError("Simulation rates must stay within [0, 1].")
    rng = random.Random(seed)
    counts = {"higher": 0, "lower": 0, "no_clear_difference": 0, "insufficient_sample": 0}
    for _ in range(trials):
        treated = sum(rng.random() < treated_rate for _ in range(sample_size))
        baseline = sum(rng.random() < base_rate for _ in range(sample_size))
        verdict = compare_rates(
            (treated, sample_size), (baseline, sample_size), min_sample=min_sample
        ).verdict
        counts[verdict] += 1
    claimed = counts["higher"] + counts["lower"]
    if lift > 0:
        correct, wrong = counts["higher"], counts["lower"]
    elif lift < 0:
        correct, wrong = counts["lower"], counts["higher"]
    else:
        correct, wrong = 0, 0
    return SimulationResult(
        trials=trials, sample_size=sample_size, base_rate=base_rate, lift=lift,
        detection_rate=correct / trials,
        false_claim_rate=(claimed if lift == 0 else 0) / trials,
        wrong_direction_rate=wrong / trials,
        insufficient_rate=counts["insufficient_sample"] / trials,
    )
