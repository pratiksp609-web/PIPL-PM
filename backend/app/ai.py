"""Optional AI analysis through the Anthropic API (backend only; the key never reaches the browser).

If ANTHROPIC_API_KEY is not set, callers fall back to deterministic template reports.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from .config import get_settings

log = logging.getLogger("pipl.ai")
settings = get_settings()


class AIUnavailable(Exception):
    """AI is not configured or the request failed; the caller should use the non-AI fallback."""


class ProjectNote(BaseModel):
    code: str
    health: str = Field(description="on_track | at_risk | delayed | critical | unknown")
    note: str


class Analysis(BaseModel):
    overall_health: str = Field(description="on_track | at_risk | delayed | critical | unknown")
    summary: str
    confirmed_facts: list[str] = Field(description="Statements directly supported by the supplied records")
    estimates: list[str] = Field(description="Estimates or assumptions, each stating what it is based on")
    risks: list[str]
    data_issues: list[str] = Field(description="Missing updates, inconsistent or incomplete data")
    recommendations: list[str] = Field(description="Actionable next steps, clearly marked as recommendations")
    project_notes: list[ProjectNote]


SYSTEM_PROMPT = """You are a project controls analyst for PIPL, a company delivering engineering, manufacturing, \
procurement and turnkey projects. You receive a JSON export of the company's actual project records for a reporting \
period: projects, tasks, progress updates, quotations, client purchase orders, verified client payments \
(receivables computed as X - Y = Z), BOM procurement and supplier deliveries, plus rule-based data checks.

Analyse only what the records show. Do not invent progress, payments, dates, events or monetary values, and do not \
perform new arithmetic on money beyond restating the supplied figures. If information is missing, say it is missing.

Separate your output strictly:
- confirmed_facts: only statements directly supported by the records (cite project codes and figures as given).
- estimates: anything inferred, such as the linear planned-progress estimate or likely slippage; say what each is based on.
- risks: schedule, financial (overdue receivables, credit/overpayment, unverified payments) and procurement risks.
- data_issues: missing updates, inconsistent values, missing documents, fields that need verification.
- recommendations: concrete next actions, each naming the project and the owner role where possible.
Keep each item to one or two sentences. Write in plain business English."""


def analyze(report_data: dict) -> dict:
    if not settings.ai_enabled:
        raise AIUnavailable("AI provider is not configured (set ANTHROPIC_API_KEY on the server).")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AIUnavailable("The anthropic package is not installed") from exc

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=settings.ai_timeout_seconds, max_retries=2)
    payload = json.dumps(report_data, default=str)
    try:
        response = client.messages.parse(
            model=settings.ai_model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": f"Project records for analysis:\n<records>\n{payload}\n</records>"}],
            output_format=Analysis,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable("The AI provider rejected the API key") from exc
    except anthropic.RateLimitError as exc:
        raise AIUnavailable("The AI provider is rate limiting requests; try again later") from exc
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"The AI provider returned an error ({exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable("Could not reach the AI provider") from exc
    if response.stop_reason == "refusal":
        raise AIUnavailable("The AI provider declined to analyse this report")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AIUnavailable("The AI response was incomplete")
    log.info("ai analysis completed", extra={"model": response.model, "input_tokens": response.usage.input_tokens,
                                             "output_tokens": response.usage.output_tokens})
    result = response.parsed_output.model_dump()
    result["model"] = response.model
    return result
