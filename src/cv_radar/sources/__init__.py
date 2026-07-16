"""Collection adapters for the supported first-version sources."""

from cv_radar.sources.arxiv import ArxivSource, parse_arxiv_atom
from cv_radar.sources.rss import RSSSource, parse_feed
from cv_radar.sources.semantic_scholar import SemanticScholarClient

__all__ = ["ArxivSource", "RSSSource", "SemanticScholarClient", "parse_arxiv_atom", "parse_feed"]
