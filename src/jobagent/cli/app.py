"""Root JobAgent command-line application."""

import typer

from jobagent.cli.candidate import candidate_app
from jobagent.cli.jobs import jobs_app
from jobagent.cli.optimizer import optimizer_app

app = typer.Typer(
    name="jobagent",
    help="Evidence-grounded, human-approved job hunting capabilities.",
    no_args_is_help=True,
)
app.add_typer(candidate_app, name="candidate")
app.add_typer(jobs_app, name="jobs")
app.add_typer(optimizer_app, name="optimizer")


if __name__ == "__main__":
    app()
