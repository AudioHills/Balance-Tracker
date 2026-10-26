"""Repository checks that run in CI: no secrets committed, and security settings that must not regress."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Each pattern is split so this file doesn't match itself
SECRET_PATTERNS = {
    "AWS access key": "AK" + r"IA[0-9A-Z]{16}",
    "GitHub token": "gh" + r"[pousr]_[A-Za-z0-9]{36,}",
    "GitHub fine-grained token": "github" + r"_pat_[A-Za-z0-9_]{40,}",
    "Anthropic/OpenAI key": "s" + r"k-(ant-)?[A-Za-z0-9_-]{20,}",
    "Slack token": "xo" + r"x[abposr]-[A-Za-z0-9-]{10,}",
    "Google API key": "AI" + r"za[0-9A-Za-z_-]{35}",
    "private key": "-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----",
    "stored app secret": "dpa" + r"pi2?:[A-Za-z0-9+/=]{16,}",
    "password in code": r"(?i)(passw(or)?d|secret|api_?key|token)\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']",
}
ALLOWED = {"password in code": [r"placeholder", r"setPlaceholderText"]}


def tracked_files() -> list[Path]:
    if shutil.which("git") and (ROOT / ".git").exists():
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / f for f in out.splitlines() if (ROOT / f).is_file()]
    return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def test_no_secrets_are_committed():
    found = []
    for path in tracked_files():
        if path.suffix in {".png", ".ico", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in SECRET_PATTERNS.items():
            for m in re.finditer(pattern, text):
                line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end())]
                if not any(re.search(a, line) for a in ALLOWED.get(name, [])):
                    found.append(f"{path.relative_to(ROOT)}: {name}: {m.group()[:12]}…")
    assert not found, "Possible secrets committed:\n" + "\n".join(found)


def test_no_personal_data_files_are_committed():
    names = {p.name for p in tracked_files()}
    assert not names & {"data.json", "secrets.json", ".env"}
    assert not [n for n in names if n.startswith(("BalanceTracker-sync", "BalanceTracker-backup"))]


def test_web_app_keeps_its_content_security_policy():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert csp, "web/index.html lost its Content-Security-Policy"
    policy = dict(part.strip().split(" ", 1) for part in csp.group(1).split(";") if part.strip())
    assert policy["default-src"] == "'none'" and policy["script-src"] == "'self'"
    assert policy["connect-src"] == "'self'" and policy["object-src"] == "'none'" and policy["base-uri"] == "'none'"
    assert '<meta name="referrer" content="no-referrer">' in html


def test_web_app_has_no_inline_scripts_or_handlers():
    """The CSP blocks them, so one would silently break the app; and they're how injected markup runs."""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    for f in (ROOT / "web").glob("*.js"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+=[\"'$]", text), f"inline event handler in {f.name}"
        assert "eval(" not in text and "new Function" not in text, f"eval in {f.name}"


def test_offline_cache_covers_every_script():
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    for f in (ROOT / "web").glob("*.js"):
        if f.name != "sw.js":
            assert f'"{f.name}"' in sw, f"{f.name} isn't in the service worker's offline list"


@pytest.mark.parametrize("name", ["build.yml", "pages.yml"])
def test_workflows_use_least_privilege(name):
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    top = text.split("jobs:", 1)[0]
    assert re.search(r"^permissions:\n  contents: read", top, re.M), f"{name} must default to read-only"
    assert "persist-credentials: false" in text
    assert "pull_request_target" not in text  # would run untrusted code with secrets
