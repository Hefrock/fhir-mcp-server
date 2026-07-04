"""
Tests for the FastMCP `instructions` string builder.

The instructions the AI sees before every tool call carry the backend label
(when set) so a multi-backend Claude session can route correctly. The base
instructions must always be present; the label is a prefix, not a replacement.
"""

from fhir_mcp_server import fhir_client
from fhir_mcp_server.server import _BASE_INSTRUCTIONS, _build_instructions


def test_base_instructions_present_without_label():
    fhir_client.FHIR_SERVER_LABEL = None
    result = _build_instructions()
    assert result == _BASE_INSTRUCTIONS
    assert "Backend:" not in result


def test_label_prepended_when_set():
    fhir_client.FHIR_SERVER_LABEL = "Synthea lab"
    result = _build_instructions()
    assert result.startswith("[Backend: Synthea lab]")
    # Base instructions still fully present after the label header
    assert _BASE_INSTRUCTIONS in result


def test_label_supports_multiline_descriptions():
    fhir_client.FHIR_SERVER_LABEL = (
        "Epic PROD — real patient data. Do NOT use for demos."
    )
    result = _build_instructions()
    assert "Epic PROD" in result
    assert "Do NOT use for demos" in result
    assert _BASE_INSTRUCTIONS in result
