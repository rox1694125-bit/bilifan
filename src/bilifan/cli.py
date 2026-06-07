import typer

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    pass


@app.command()
def summarize(url: str) -> None:
    """Prepare a local Bilifan run for one Bilibili current-P URL."""
    typer.echo(f"preflight pending for {url}")


def main() -> None:
    app()
