"""Tools available to the autonomous research agent."""

from .web_search import WebSearchTool
from .arxiv_search import ArxivSearchTool
from .pdf_reader import PdfReaderTool
from .memory import MemoryTool
from .synthesizer import SynthesizerTool
from .wikipedia import WikipediaTool
from .web_fetch import WebFetchTool
from .semantic_scholar import SemanticScholarTool
from .hacker_news import HackerNewsTool
from .rss import RssTool
from .github_search import GithubSearchTool
from .system_monitor import SystemMonitor
from .cache import DiskCache
from .chunker import chunk_text
from .skills import SkillRegistry
from .phoenix_tracer import maybe_setup_phoenix

__all__ = [
    "WebSearchTool",
    "ArxivSearchTool",
    "PdfReaderTool",
    "MemoryTool",
    "SynthesizerTool",
    "WikipediaTool",
    "WebFetchTool",
    "SemanticScholarTool",
    "HackerNewsTool",
    "RssTool",
    "GithubSearchTool",
    "SystemMonitor",
    "DiskCache",
    "chunk_text",
    "SkillRegistry",
    "maybe_setup_phoenix",
]
