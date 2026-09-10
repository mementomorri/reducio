"""Analyzer agent using the shared, versioned source metrics."""

from reducto.analysis import analyze_files
from reducto.models import AnalyzeRequest, AnalyzeResult
from reducto.workspace import Workspace


class AnalyzerAgent:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResult:
        return analyze_files(
            request.files or self.workspace.list_files(),
            self.workspace.cfg,
            request.path,
        )
