"""Root JobAgent command-line application."""

import sys

import typer

from jobagent.cli.applications import applications_app
from jobagent.cli.candidate import candidate_app
from jobagent.cli.conversations import conversations_app
from jobagent.cli.harness import harness_app
from jobagent.cli.jobs import jobs_app
from jobagent.cli.mailbox import mailbox_app
from jobagent.cli.optimizer import optimizer_app
from jobagent.cli.outreach import outreach_app
from jobagent.cli.patrol import patrol_app
from jobagent.cli.profile import profile_app

app = typer.Typer(
    name="jobagent",
    help="Evidence-grounded, human-approved job hunting capabilities.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Emit UTF-8 JSON regardless of the console's default encoding."""
    # Resume and JD text is routinely non-ASCII; a legacy console codec such as
    # cp936 would otherwise raise UnicodeEncodeError while writing valid output.
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower().replace("-", "") != "utf8":
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="backslashreplace")


app.add_typer(candidate_app, name="candidate")
app.add_typer(jobs_app, name="jobs")
app.add_typer(optimizer_app, name="optimizer")
app.add_typer(applications_app, name="applications")
app.add_typer(harness_app, name="harness")
app.add_typer(outreach_app, name="outreach")
app.add_typer(conversations_app, name="conversations")
app.add_typer(patrol_app, name="patrol")
app.add_typer(profile_app, name="profile")
app.add_typer(mailbox_app, name="mailbox")


if __name__ == "__main__":
    app()
