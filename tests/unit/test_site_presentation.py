"""Keep project links and standalone report styling aligned with the landing page."""

import re
import shlex
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from typer.main import get_command

from reducio.analysis import analyze_files
from reducio.cli import app
from reducio.models import AppConfig
from reducio.visual_report import _LOGO_SVG, _REPORT_STYLE, _figures, html_report

SITE = Path(__file__).resolve().parents[2] / "docs/index.html"
PROJECT = "https://mementomorri.github.io/reducio/"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a":
            self.hrefs.append(attrs["href"])


def test_landing_links_use_canonical_repo_and_project_path():
    source = SITE.read_text()
    links = Links()
    links.feed(source)
    assert "alexkarsten/reducio" not in source
    assert "github.com/mementomorri/reducio/blob/main/docs/GITHUB_CI.md" in source
    assert "Forge from Source" not in source
    for href in links.hrefs:
        if href.startswith("#"):
            assert href[1:] in links.ids
        elif href.startswith("https://github.com/"):
            assert href.startswith("https://github.com/mementomorri/reducio")
        else:
            assert urljoin(PROJECT, href).startswith(PROJECT)
    assert "./" in links.hrefs and "dashboard/" in links.hrefs


def test_landing_has_no_emoji_feature_icons():
    source = SITE.read_text()
    assert "feature-icon" not in source
    assert not re.search(r"[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f]", source)


def test_landing_and_dashboard_share_logo_and_lowercase_wordmark():
    source = SITE.read_text()
    report = html_report(analyze_files([], AppConfig()))
    landing_logo = re.search(r'<div class="logo-icon"[^>]*>(.*?)</div>', source, re.S)[1]
    assert re.findall(r'<path d="([^"]+)"', landing_logo) == re.findall(
        r'<path d="([^"]+)"', _LOGO_SVG
    )
    assert _LOGO_SVG in report
    for html, logo_class in ((source, "logo"), (report, "brand")):
        brand = re.search(rf'<a [^>]*class="{logo_class}"[^>]*>(.*?)</a>', html, re.S)[1]
        assert re.sub(r"<[^>]+>", "", brand).strip() == "reducio"
    for selector in (".logo", ".hero h1", ".footer-logo"):
        style = re.search(re.escape(selector) + r"\s*\{([^}]+)", source)[1]
        assert "font-family: Georgia, serif" in style
        assert "text-transform: lowercase" in style
    assert "font-family:Georgia,serif" in _REPORT_STYLE
    assert "text-transform:lowercase" in _REPORT_STYLE


def test_report_palette_matches_landing_without_external_assets():
    source = SITE.read_text()
    palette = r"(--[\w-]+):\s*(#[a-fA-F0-9]{6})"
    landing = dict(re.findall(palette, source))
    dashboard = dict(re.findall(palette, _REPORT_STYLE))
    assert len(dashboard) >= 8
    assert all(landing[key] == value for key, value in dashboard.items())
    report = html_report(analyze_files([], AppConfig()))
    assert "@import" not in _REPORT_STYLE and "url(" not in _REPORT_STYLE
    assert "<link " not in report
    assert 'id="measurements"' in report
    assert 'aria-label="Report navigation"' in report


def test_chart_backgrounds_and_text_match_dark_theme():
    for figure in _figures(analyze_files([], AppConfig())):
        assert figure.layout.paper_bgcolor == "#12101f"
        assert figure.layout.plot_bgcolor == "#12101f"
        assert figure.layout.font.color == "#f0e6d3"
        assert figure.layout.title.font.color == "#f0d78c"


def test_landing_demo_uses_supported_cli_commands_without_execution():
    commands = re.findall(
        r'<p><span class="terminal-prompt">\$</span> ([^<]+)</p>', SITE.read_text()
    )
    assert len(commands) == 3
    cli = get_command(app)
    for example in commands:
        program, name, *args = shlex.split(unescape(example))
        assert program == "reducio"
        # Parsing validates flags and required arguments without applying any plan.
        with cli.commands[name].make_context(name, args) as context:
            if name == "idiomatize":
                assert context.params["dry_run"] is True
            else:
                assert name in {"analyze", "compare"}
                assert context.params["report"] is True
                assert context.params["format"] == "all"


def test_landing_copy_discloses_limits_and_links_enhancements():
    source = SITE.read_text()
    for old_claim in (
        "preserving every ounce of functionality",
        "Your secrets stay yours",
        "instant restoration",
        "deduplicate --commit",
        "Lines consumed:",
    ):
        assert old_claim not in source
    for disclosure in (
        "Automatic modification is not production-safe",
        "call sites are not rewritten",
        "Model planning sends source code",
        "Hotspots use the cyclomatic threshold",
        "reports",
        "embeddings",
        "ROADMAP.md#enhancement-opportunities",
    ):
        assert disclosure in source
    roadmap = SITE.parent.parent / "ROADMAP.md"
    assert "## Enhancement opportunities" in roadmap.read_text()
