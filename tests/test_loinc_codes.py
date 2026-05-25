"""Tests for the LOINC code lookup helpers."""

from fhir_mcp_server import loinc_codes


class TestResolve:
    def test_friendly_name(self):
        assert loinc_codes.resolve("heart_rate") == "8867-4"

    def test_case_and_separator_insensitive(self):
        assert loinc_codes.resolve("Heart Rate") == "8867-4"
        assert loinc_codes.resolve("heart-rate") == "8867-4"

    def test_raw_code_passes_through(self):
        assert loinc_codes.resolve("8480-6") == "8480-6"

    def test_unknown_name_passes_through(self):
        assert loinc_codes.resolve("zorblax") == "zorblax"


class TestDescribe:
    def test_known_code(self):
        assert loinc_codes.describe("8867-4") == "heart_rate"

    def test_unknown_code(self):
        assert loinc_codes.describe("9999-9") == "9999-9"
