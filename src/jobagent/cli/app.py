"""Root JobAgent command-line application."""

import typer

from jobagent.cli.candidate import candidate_app

app = typer.Typer(
    name="jobagent",
    help="Evidence-grounded, human-approved job hunting capabilities.",
    no_args_is_help=True,
)
app.add_typer(candidate_app, name="candidate")


if __name__ == "__main__":
    app()
