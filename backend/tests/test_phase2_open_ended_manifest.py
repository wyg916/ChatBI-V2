import json
from collections import Counter
from pathlib import Path

from app.integration.question_router import QuestionRouter
from app.services.conversations import extract_slots


MANIFEST = Path(__file__).parents[2] / "evaluation" / "golden" / "phase2-open-ended-60.json"


class _NoModelGateway:
    def classify(self, *_args, **_kwargs):
        raise AssertionError("The frozen route corpus must not require a model classification fallback")


def test_phase2_open_ended_60_has_required_distribution_and_route_coverage():
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 60
    assert len({item["id"] for item in cases}) == 60
    assert len({item["question"] for item in cases}) == 60
    assert Counter(item["category"] for item in cases) == {
        "DATA_QUERY": 15,
        "KNOWLEDGE_QUERY": 10,
        "HYBRID_OR_COMPLEX": 10,
        "FOLLOW_UP": 10,
        "GENERAL_CHAT": 5,
        "FILE_QUERY": 5,
        "MULTIMODAL_QUERY": 5,
    }

    router = QuestionRouter(_NoModelGateway())
    passed = 0
    follow_up_passed = 0
    for item in cases:
        question = item["question"]
        if item["category"] == "FOLLOW_UP":
            _, question = extract_slots(question, item.get("context"))
        route = router.classify(question, attachment_kinds=set(item.get("attachment_kinds", [])))
        passed += route.value == item["expected_route"]
        if item["category"] == "FOLLOW_UP":
            follow_up_passed += route.value == item["expected_route"]
    assert passed == 60
    assert follow_up_passed == 10
