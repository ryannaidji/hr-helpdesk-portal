import pytest

from app.escalation import ESCALATE_AT, Context, level_for, score_message


@pytest.mark.parametrize("message", [
    "My manager keeps harassing me at work",
    "I was discriminated against in my review",
    "I am being retaliated against after I complained",
])
def test_first_person_reports_escalate(message):
    assert score_message(message).escalate


def test_safety_is_critical_and_not_damped_by_question_form():
    score = score_message("What should I do if I want to kill myself?")
    assert score.level == "critical" and score.escalate


@pytest.mark.parametrize("message", [
    "What is the harassment policy?",
    "How do I report discrimination?",
    "Is retaliation prohibited?",
])
def test_informational_questions_do_not_escalate(message):
    assert not score_message(message).escalate


def test_benign_message_scores_zero():
    score = score_message("How many sick days do we get?")
    assert score.score == 0 and score.level == "none" and score.reasons == []


def test_secondary_signals_count_half():
    assert score_message("My boss is harassing me, I will contact a lawyer").score == 60 + 20


def test_stacked_mild_signals_stay_below_serious_signal():
    mild = score_message("urgent, unacceptable, I am overwhelmed")
    assert mild.score < ESCALATE_AT


def test_context_adds_points():
    base = score_message("I am owed money, I have not been paid").score
    assert score_message("I am owed money, I have not been paid", Context(recent_denials=3)).score == base + 20
    assert score_message("I am owed money, I have not been paid", Context(recent_denials=2)).score == base
    assert score_message("hello", Context(low_retrieval_confidence=True)).score == 15
    assert score_message("hello", Context(prior_open_escalations=2)).score == 10


def test_score_is_capped():
    assert score_message("I was assaulted and harassed, my lawyer says retaliation", Context(recent_denials=9)).score == 100


@pytest.mark.parametrize("score,level", [(0, "none"), (24, "none"), (25, "watch"), (49, "watch"),
                                         (50, "high"), (69, "high"), (70, "critical"), (100, "critical")])
def test_level_boundaries(score, level):
    assert level_for(score) == level


def test_regression_gerund_self_harm_phrase_escalates():
    # Found by the routing eval: the pattern originally matched only "hurt myself".
    assert score_message("I feel like hurting myself").level == "critical"
