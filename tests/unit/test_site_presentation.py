"""Keep project links and standalone report styling aligned with the landing page."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from reducto.analysis import analyze_files
from reducto.models import AppConfig
from reducto.visual_report import _REPORT_STYLE, _figures, html_report

SITE = Path(__file__).resolve().parents[2] / "docs/index.html"
PROJECT = "https://mementomorri.github.io/reducto/"


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
    assert "alexkarsten/reducto" not in source
    assert "github.com/mementomorri/reducto.git" in source
    for href in links.hrefs:
        if href.startswith("#"):
            assert href[1:] in links.ids
        elif href.startswith("https://github.com/"):
            assert href.startswith("https://github.com/mementomorri/reducto")
        else:
            assert urljoin(PROJECT, href).startswith(PROJECT)
    assert "./" in links.hrefs and "dashboard/" in links.hrefs


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
