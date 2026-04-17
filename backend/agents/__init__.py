"""Agent registry — exports all four pipeline agents."""

from agents.ingestion import ingest
from agents.classifier import classify
from agents.cluster import cluster
from agents.resolver import resolve

__all__ = ["ingest", "classify", "cluster", "resolve"]