import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import typer
import uvicorn

from .chunking import ChunkingError, LongVideoConfirmationRequired
from .config import (
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    write_consent,
)
from .diagnostics import redact_text
from .media import MediaDownloadError
from .metadata import MetadataIngestError
from .pipeline import (
    PipelineRequest,
    PipelineRunError,
    run_summarize_pipeline,
    validate_language,
    validate_output_format,
)
from .renderer import PdfExportError
from .retry import RetryError, retry_run
from .summarizer import SummarizationError, validate_summary_style
from .transcript import TranscriptError
from .web.app import create_app
from .web.security import generate_token

app = typer.Typer(no_args_is_help=True)

LOCAL_PROCESSING_NOTICE = (
    "Bilifan local processing consent:\n"
    "Bilifan prepares runs locally on this machine, downloads current-P audio for "
    "local processing, and writes output files under the selected --out directory. "
    "By default it calls your configured Codex CLI to summarize transcript chunks, "
    "which may send transcript text to the model service behind that Codex account."
)
COOKIES_NOTICE = (
    "Bilifan cookies notice:\n"
    "Cookie options are reserved for local use only. Bilifan does not store cookies "
    "or cookie file names in reports or config."
)
OPEN_BROWSER_DELAY_SECONDS = 0.5
OPEN_BROWSER_READY_TIMEOUT_SECONDS = 10.0
OPEN_BROWSER_RETRY_SECONDS = 0.1


@app.callback()
def callback() -> None:
    pass


@app.command()
def summarize(
    url: str,
    out: Path = typer.Option(Path("./outputs"), "--out"),
    cookies_from_browser: str | None = typer.Option(None, "--cookies-from-browser"),
    cookies_file: Path | None = typer.Option(None, "--cookies-file"),
    output_format: str = typer.Option("html,pdf", "--format"),
    transcriber: str = typer.Option("auto", "--transcriber"),
    language: str = typer.Option("auto", "--language"),
    force_whisper: bool = typer.Option(False, "--force-whisper"),
    llm_provider: str = typer.Option("codex-exec", "--llm-provider"),
    llm_model: str = typer.Option("gpt-5.5", "--llm-model"),
    summary_template: str = typer.Option("学习笔记", "--summary-template", "--style"),
    with_frames: bool = typer.Option(False, "--with-frames"),
    with_diagrams: bool = typer.Option(False, "--with-diagrams"),
    require_pdf: bool = typer.Option(False, "--require-pdf"),
    allow_long_video: bool = typer.Option(False, "--allow-long-video"),
    yes_i_understand: bool = typer.Option(False, "--yes-i-understand"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    debug_log: bool = typer.Option(False, "--debug-log"),
) -> None:
    """Prepare a local Bilifan run for one Bilibili current-P URL."""
    if debug_log:
        raise typer.BadParameter("--debug-log is reserved for a later slice.")
    try:
        validate_output_format(output_format)
        validate_language(language)
        summary_template = validate_summary_style(summary_template)
    except ValueError as exc:
        raise typer.BadParameter(redact_text(str(exc))) from exc
    except SummarizationError as exc:
        raise typer.BadParameter(redact_text(str(exc))) from exc

    uses_cookies = cookies_from_browser is not None or cookies_file is not None
    _ensure_consent(uses_cookies=uses_cookies, yes_i_understand=yes_i_understand)

    try:
        result = run_summarize_pipeline(
            PipelineRequest(
                url=url,
                out=out,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                output_format=output_format,
                transcriber=transcriber,
                language=language,
                force_whisper=force_whisper,
                llm_provider=llm_provider,
                llm_model=llm_model,
                summary_template=summary_template,
                with_frames=with_frames,
                with_diagrams=with_diagrams,
                require_pdf=require_pdf,
                allow_long_video=allow_long_video,
                yes_i_understand=yes_i_understand,
                overwrite=overwrite,
                confirm_long_video=lambda message: typer.confirm(
                    f"{message} Continue?"
                ),
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(redact_text(str(exc))) from exc
    except PipelineRunError as exc:
        if exc.exit_code == 2:
            raise typer.BadParameter(redact_text(str(exc))) from exc
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(exc.exit_code) from exc
    except (
        MetadataIngestError,
        MediaDownloadError,
        TranscriptError,
        ChunkingError,
        SummarizationError,
        PdfExportError,
        LongVideoConfirmationRequired,
    ) as exc:
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Prepared Bilifan run: {result.run_key}")


@app.command()
def retry(
    run_dir: Path,
    from_stage: str = typer.Option("", "--from"),
    output_format: str = typer.Option("html,pdf", "--format"),
    llm_provider: str = typer.Option("codex-exec", "--llm-provider"),
    llm_model: str = typer.Option("gpt-5.5", "--llm-model"),
    summary_template: str = typer.Option("学习笔记", "--summary-template", "--style"),
    with_frames: bool = typer.Option(False, "--with-frames"),
    with_diagrams: bool = typer.Option(False, "--with-diagrams"),
    require_pdf: bool = typer.Option(False, "--require-pdf"),
) -> None:
    """Retry summarization, render, or bundle stages for an existing run directory."""
    if not from_stage:
        raise typer.BadParameter("--from must be summarization, render, or bundle.")
    try:
        result = retry_run(
            run_dir,
            from_stage=from_stage,
            output_format=output_format,
            llm_provider=llm_provider,
            llm_model=llm_model,
            summary_template=summary_template,
            with_frames=with_frames,
            with_diagrams=with_diagrams,
            require_pdf=require_pdf,
        )
    except RetryError as exc:
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Retried Bilifan run: {result.run_key}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    public_url: str | None = typer.Option(None, "--public-url"),
    strict_port: bool = typer.Option(False, "--strict-port"),
    no_open: bool = typer.Option(False, "--no-open"),
) -> None:
    """Serve the local Bilifan Web UI."""
    host = _ensure_localhost_host(host)
    public_entry_url = _normalize_public_url(public_url) if public_url else None
    selected_port = _find_available_port(host, port)
    if strict_port and selected_port != port:
        raise typer.BadParameter(f"--port {port} is already in use.")
    token = generate_token()
    app_instance = create_app(
        outputs=Path("./outputs"),
        token=token,
        open_browser=not no_open,
        public_url=public_entry_url,
    )
    url = f"http://127.0.0.1:{selected_port}/"
    typer.echo(f"Local URL: {url}")
    if public_entry_url:
        typer.echo(f"Public URL: {public_entry_url}")
    if not no_open:
        _schedule_browser_open(url)
    uvicorn.run(app_instance, host=host, port=selected_port, log_level="info")


def _ensure_consent(*, uses_cookies: bool, yes_i_understand: bool) -> None:
    config_path = default_config_path()
    needs_local_notice = not has_local_processing_consent(config_path)
    needs_cookies_notice = uses_cookies and not has_cookies_consent(config_path)

    if not needs_local_notice and not needs_cookies_notice:
        return

    if yes_i_understand:
        write_consent(
            config_path,
            local_processing=needs_local_notice,
            cookies=needs_cookies_notice,
            accepted_via="yes-i-understand",
        )
        return

    if needs_local_notice:
        typer.echo(LOCAL_PROCESSING_NOTICE)
        accepted = typer.confirm("Continue?", default=False)
        if not accepted:
            raise typer.Exit(1)
        write_consent(config_path, local_processing=True, accepted_via="prompt")

    if needs_cookies_notice:
        typer.echo(COOKIES_NOTICE)
        accepted = typer.confirm("Continue with cookies?", default=False)
        if not accepted:
            raise typer.Exit(1)
        write_consent(config_path, cookies=True, accepted_via="prompt")


def _ensure_localhost_host(host: str) -> str:
    if host != "127.0.0.1":
        raise typer.BadParameter("MVP only supports --host 127.0.0.1.")
    return host


def _normalize_public_url(public_url: str) -> str:
    value = public_url.strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise typer.BadParameter("--public-url must start with https://")
    if parsed.query or parsed.fragment:
        raise typer.BadParameter("--public-url must not include query string or fragment.")
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, f"{path}/", "", ""))


def _find_available_port(host: str, preferred_port: int) -> int:
    first_port = _validate_port(preferred_port)
    last_port = min(65535, first_port + 99)
    for port in range(first_port, last_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise typer.BadParameter("Could not find an available local port.")


def _validate_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise typer.BadParameter("--port must be between 1 and 65535.")
    return port


def _schedule_browser_open(url: str) -> None:
    timer = threading.Timer(OPEN_BROWSER_DELAY_SECONDS, _open_browser_when_ready, args=(url,))
    timer.daemon = True
    timer.start()


def _open_browser_when_ready(url: str) -> None:
    deadline = time.monotonic() + OPEN_BROWSER_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _local_url_ready(url):
            _open_browser(url)
            return
        time.sleep(OPEN_BROWSER_RETRY_SECONDS)


def _local_url_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.2) as response:
            return 200 <= response.status < 500
    except OSError:
        return False


def _open_browser(url: str) -> None:
    webbrowser.open(url)


def main() -> None:
    app()
