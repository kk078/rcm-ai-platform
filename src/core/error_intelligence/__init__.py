"""Aethera AI — Error Intelligence module.

Automatically captures, stores, and AI-analyzes every unhandled error
so the team has root-cause analysis, suggested fixes, and severity ratings
without manually digging through logs.
"""
from src.core.error_intelligence.analyzer import analyze_error, ErrorAnalysis
from src.core.error_intelligence.capture import capture_error

__all__ = ["analyze_error", "ErrorAnalysis", "capture_error"]
