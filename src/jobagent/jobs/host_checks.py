"""Three-state page settling policy; the host performs any authorized reload."""

from jobagent.schemas.host_checks import HostPageObservation


def page_decision(observation: HostPageObservation) -> dict[str, object]:
    login_failure = observation.state == "login_redirect"
    action = (
        "request_user_login"
        if login_failure
        else "inspect_read_only"
        if observation.state == "logged_in"
        else "reload_once"
        if observation.reload_count == 0
        else "unconfirmed"
    )
    return {
        "source": observation.source,
        "surface": observation.surface,
        "state": observation.state,
        "action": action,
        "login_failure": login_failure,
        "needs_user_action": login_failure,
        "notification_required": login_failure,
        "reply_confirmed": False,
        "no_reply_confirmed": False,
        "search_gate_result_required": login_failure and observation.surface == "search",
        "evidence_reference": observation.evidence_reference,
    }
