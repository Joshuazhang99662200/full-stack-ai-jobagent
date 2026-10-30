from datetime import UTC, datetime, timedelta

from tests.rules.test_dynamic_registry import request


def profile(values, *, candidate_id="CAND_SYNTHETIC"):
    from jobagent.rules.service import activate_proposal, make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation

    current = None
    for index, (name, value) in enumerate(values.items()):
        at = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=index)
        change = request(name, value)
        change.candidate_id = candidate_id
        change.expected_version = current.version if current else None
        proposal = make_proposal(change, current, now=at)
        current = activate_proposal(
            proposal,
            RuleConfirmation(
                proposal_id=proposal.proposal_id,
                question_digest=proposal.question_digest,
                answer="Synthetic exact configuration approval",
                actor_id="synthetic owner",
                confirmed_at=at,
            ),
            current,
        )
    return current


def test_polling_resumes_on_aligned_slot_after_weekend():
    from jobagent.rules.evaluation import evaluate_poll

    rules = profile(
        {
            "POLL_INTERVAL_HOURS": 3,
            "POLL_ALIGN_MINUTE": "05:13",
            "POLL_TIMEZONE": "Asia/Shanghai",
            "WEEKEND_PAUSE_START": {"weekday": 4, "time": "20:00"},
            "WEEKEND_PAUSE_END": {"weekday": 6, "time": "20:00"},
        }
    )
    friday = datetime.fromisoformat("2026-10-30T20:00:00+08:00")
    decision = evaluate_poll(rules, friday)
    assert not decision.due
    assert decision.next_poll_at == datetime.fromisoformat("2026-11-01T20:13:00+08:00")
    sunday = evaluate_poll(rules, datetime.fromisoformat("2026-11-01T20:00:00+08:00"))
    assert not sunday.due and sunday.active


def test_abandonment_uses_configured_hours_and_never_rewrites_terminal_history():
    from jobagent.rules.evaluation import evaluate_abandonment
    from jobagent.schemas.rule_evaluation import AbandonmentObservation

    rules = profile(
        {
            "ABANDON_HOURS": 72,
            "RESUME_STAGE_IN_ABANDON_LINE": True,
            "ABANDON_IMMEDIATE_REASONS": ["employer_rejected", "job_closed"],
        }
    )
    at = datetime(2026, 10, 1, tzinfo=UTC)
    observation = AbandonmentObservation(
        pipeline_id="SYN_PIPE",
        sent_at=at,
        stage="resume",
        last_evidence="synthetic confirmed sent receipt",
        last_checked_at=at,
    )
    assert not evaluate_abandonment(rules, observation, at + timedelta(hours=60)).abandoned
    decision = evaluate_abandonment(rules, observation, at + timedelta(hours=73))
    assert decision.abandoned and decision.abandoned_at is not None
    old = observation.model_copy(update={"terminal": True})
    assert not evaluate_abandonment(rules, old, at + timedelta(hours=100)).changed
    active = observation.model_copy(
        update={"last_substantive_activity_at": at + timedelta(hours=60)}
    )
    assert not evaluate_abandonment(rules, active, at + timedelta(hours=73)).abandoned


def test_unverified_closed_job_cannot_cause_immediate_abandonment():
    from jobagent.rules.evaluation import evaluate_abandonment
    from jobagent.schemas.rule_evaluation import AbandonmentObservation

    rules = profile(
        {
            "ABANDON_HOURS": 100,
            "RESUME_STAGE_IN_ABANDON_LINE": True,
            "ABANDON_IMMEDIATE_REASONS": ["job_closed"],
        }
    )
    at = datetime(2026, 10, 1, tzinfo=UTC)
    observation = AbandonmentObservation(
        pipeline_id="SYN",
        sent_at=at,
        immediate_reason="job_closed",
        last_evidence="unverified disappearance",
        last_checked_at=at,
    )
    assert not evaluate_abandonment(rules, observation, at).abandoned


def test_ratio_only_proposes_and_backlog_never_discards():
    from jobagent.rules.evaluation import evaluate_backlog, evaluate_ratio
    from jobagent.schemas.rule_evaluation import RatioObservation

    rules = profile({"RATIO_TRIGGER_FACTOR": 0.7, "PENDING_BACKLOG_ASK_THRESHOLD": 5})
    result = evaluate_ratio(
        rules,
        RatioObservation(
            sliced_cumulative_rate=0.1,
            historical_rate=0.5,
            denominator=20,
            sustained=True,
            window_valid=True,
            evidence_ref="synthetic metric slice",
        ),
    )
    assert result.propose_diagnosis and result.proposal_only
    assert evaluate_backlog(rules, 6).needs_user_choice


def test_verified_immediate_reason_takes_precedence_over_resume_exemption():
    from jobagent.rules.evaluation import evaluate_abandonment
    from jobagent.schemas.rule_evaluation import AbandonmentObservation

    rules = profile(
        {
            "ABANDON_HOURS": 72,
            "RESUME_STAGE_IN_ABANDON_LINE": False,
            "ABANDON_IMMEDIATE_REASONS": ["job_closed"],
        }
    )
    at = datetime(2026, 10, 1, tzinfo=UTC)
    decision = evaluate_abandonment(
        rules,
        AbandonmentObservation(
            pipeline_id="SYN",
            sent_at=at,
            stage="resume",
            immediate_reason="job_closed",
            immediate_verified=True,
            last_evidence="synthetic verified closure",
            last_checked_at=at,
        ),
        at,
    )
    assert decision.abandoned


def test_next_poll_after_completed_slot_skips_pause():
    from jobagent.rules.evaluation import evaluate_poll

    rules = profile(
        {
            "POLL_INTERVAL_HOURS": 3,
            "POLL_ALIGN_MINUTE": "05:13",
            "POLL_TIMEZONE": "Asia/Shanghai",
            "WEEKEND_PAUSE_START": {"weekday": 4, "time": "20:00"},
            "WEEKEND_PAUSE_END": {"weekday": 6, "time": "20:00"},
        }
    )
    at = datetime.fromisoformat("2026-10-30T17:13:00+08:00")
    decision = evaluate_poll(rules, at, last_check_at=at)
    assert decision.next_poll_at == datetime.fromisoformat("2026-11-01T20:13:00+08:00")
