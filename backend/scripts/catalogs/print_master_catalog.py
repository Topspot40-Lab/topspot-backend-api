"""Render the master catalog with Chrome, falling back to Edge."""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CHROME_CANDIDATES = (shutil.which("chrome"), shutil.which("google-chrome"), os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"))
EDGE_CANDIDATES = (shutil.which("msedge"), os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"))

def find_browser() -> str:
    for candidate in (*CHROME_CANDIDATES, *EDGE_CANDIDATES):
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Chrome or Microsoft Edge is required to create the catalog PDF.")

def browser_candidates() -> tuple[str, ...]:
    """Return usable browsers in the required Chrome-then-Edge preference."""
    return tuple(candidate for candidate in (*CHROME_CANDIDATES, *EDGE_CANDIDATES)
                 if candidate and Path(candidate).exists())

def render_pdf(html_path: Path, pdf_path: Path) -> Path:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    # Use a fresh profile for each export.  A reused profile can remain locked
    # by a previously crashed headless browser and prevent all later renders.
    # Chrome may retain a Crashpad handle briefly after its print process ends;
    # cleanup errors must not discard an otherwise completed PDF on Windows.
    # Some managed Windows environments deny cleanup in the default user-temp
    # directory.  Allow the caller to provide an explicitly writable location.
    temp_root = Path(os.environ.get("TOPSPOT40_CATALOG_TEMP_DIR", tempfile.gettempdir()))
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="topspot40-catalog-browser-", dir=temp_root, ignore_cleanup_errors=True) as profile:
        for browser in browser_candidates():
            try:
                subprocess.run([
                    browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path.resolve()}",
                    html_path.resolve().as_uri(),
                ], check=True, capture_output=True, text=True)
                if pdf_path.exists():
                    return pdf_path
            except subprocess.CalledProcessError as error:
                failures.append(f"{Path(browser).name}: {error.stderr.strip() or error.returncode}")
    raise RuntimeError("Unable to generate PDF with Chrome or Edge. " + " | ".join(failures))

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(f"Generated: {render_pdf(args.html, args.output or args.html.with_suffix('.pdf'))}")

if __name__ == "__main__":
    main()
