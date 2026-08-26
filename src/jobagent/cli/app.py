"""Root JobAgent command-line application."""

import sys

import typer

from jobagent.cli.applications import applications_app
from jobagent.cli.candidate import candidate_app
from jobagent.cli.jobs import jobs_app
from jobagent.cli.optimizer import optimizer_app

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


if __name__ == "__main__":
    app()
