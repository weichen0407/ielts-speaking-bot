"""Schemas for the Be Native review processor."""

from __future__ import annotations

from subagent._shared.benative_schema import BenativeResponse, BenativeReviewItem


class BenativeReviewInput(BenativeResponse):
    """Processor input row for a user reconstruction response."""


class BenativeReviewOutput(BenativeReviewItem):
    """Processor output row for structured Be Native feedback."""
