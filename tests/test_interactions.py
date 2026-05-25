"""Tests for the local medication interaction lookup."""

from fhir_mcp_server import interactions


class TestCheckPair:
    def test_known_interaction(self):
        hit = interactions.check_pair("warfarin", "aspirin")
        assert hit is not None
        assert hit.severity == "major"

    def test_order_independent(self):
        a = interactions.check_pair("warfarin", "aspirin")
        b = interactions.check_pair("aspirin", "warfarin")
        assert a == b

    def test_brand_name_resolves(self):
        assert interactions.check_pair("Coumadin", "ASA") is not None

    def test_no_interaction(self):
        assert interactions.check_pair("acetaminophen", "loratadine") is None


class TestCheckMedications:
    def test_finds_pair_in_list(self):
        findings = interactions.check_medications(
            ["lisinopril", "warfarin", "aspirin"]
        )
        pairs = {frozenset({f["drug_a"], f["drug_b"]}) for f in findings}
        assert frozenset({"warfarin", "aspirin"}) in pairs

    def test_sorted_major_first(self):
        # simvastatin+amlodipine (moderate) and warfarin+aspirin (major)
        findings = interactions.check_medications(
            ["simvastatin", "amlodipine", "warfarin", "aspirin"]
        )
        assert findings[0]["severity"] == "major"

    def test_empty_when_no_interactions(self):
        assert interactions.check_medications(["acetaminophen", "loratadine"]) == []

    def test_single_drug_yields_nothing(self):
        assert interactions.check_medications(["warfarin"]) == []
