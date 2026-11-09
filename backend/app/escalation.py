"""Escalation scoring: a transparent, deterministic 0-100 score that decides when a human takes over.

The score runs BEFORE any LLM and can override the router, so a model error cannot keep a safety
or harassment report away from a person. The weights are hand-set judgement calls, not fitted.
"""
import re
from dataclasses import dataclass, field

ESCALATE_AT = 50
CRITICAL_AT = 70
WATCH_AT = 25
# A question about a policy ("what is the harassment policy?") is not a report of an incident.
INFORMATIONAL_DAMPING = 0.4

SIGNALS: list[tuple[str, int, str]] = [
    ("safety_threat", 75, r"\b(kill myself|suicid\w*|self[- ]harm|hurt(?:ing)? myself|threaten\w* to (?:hurt|kill)|"
                          r"threat\w* of violence|physically (?:attacked|assaulted)|assault\w*|has a weapon)\b"),
    ("harassment_discrimination", 60, r"\b(harass\w*|discriminat\w*|sexual\w* (?:comments?|advances?)|groped|"
                                      r"racist|sexist|bull(?:y|ied|ying))\b"),
    ("retaliation", 55, r"\b(retaliat\w*|punished for (?:reporting|complaining)|whistle-?blow\w*)\b"),
    ("legal", 40, r"\b(lawyer|attorney|lawsuit|sue|suing|legal action|wrongful\w*)\b"),
    ("pay_dispute", 25, r"\b(unpaid wages?|not been paid|wasn'?t paid|missing (?:pay|salary|paycheck)|underpaid)\b"),
    ("medical_accommodation", 25, r"\b(accommodation|disabilit\w*|medical condition|mental health)\b"),
    ("urgency", 10, r"\b(urgent\w*|immediately|asap|emergency)\b"),
    ("distress", 10, r"\b(unacceptable|furious|desperate|overwhelmed|can'?t take (?:it|this))\b"),
]
_COMPILED = [(name, weight, re.compile(pattern, re.I)) for name, weight, pattern in SIGNALS]
_NEVER_DAMPED = {"safety_threat"}

_FIRST_PERSON_INCIDENT = re.compile(
    r"\b(i am|i'm|i was|i've been|i have been|i feel|my (?:manager|boss|coworker|colleague|team ?lead|supervisor)|"
    r"(?:to|at|against|about|towards?|of) me|me (?:at|in|every|after)|is \w+ing me|keeps? \w+ing me)\b", re.I)
_POLICY_QUESTION = re.compile(r"(^\s*(what|how|where|when|who|which|is|are|can|does|do)\b.*\?\s*$)|\b(policy|procedure)\b", re.I)


@dataclass(frozen=True)
class Context:
    low_retrieval_confidence: bool = False
    recent_denials: int = 0  # denied authorization attempts by this user in the last 24 h
    prior_open_escalations: int = 0


@dataclass(frozen=True)
class Score:
    score: int
    level: str  # none | watch | high | critical
    reasons: list[str] = field(default_factory=list)

    @property
    def escalate(self) -> bool:
        return self.score >= ESCALATE_AT


def is_informational(message: str) -> bool:
    return bool(_POLICY_QUESTION.search(message)) and not _FIRST_PERSON_INCIDENT.search(message)


def level_for(score: int) -> str:
    if score >= CRITICAL_AT:
        return "critical"
    if score >= ESCALATE_AT:
        return "high"
    return "watch" if score >= WATCH_AT else "none"


def score_message(message: str, context: Context | None = None) -> Score:
    context = context or Context()
    informational = is_informational(message)
    total = 0.0
    reasons: list[str] = []
    matched = [(name, weight) for name, weight, rx in _COMPILED if rx.search(message)]
    # Strongest signal counts in full, the others at half, so a stack of mild keywords
    # cannot outrank one serious signal.
    matched.sort(key=lambda item: -item[1])
    for position, (name, weight) in enumerate(matched):
        points = weight if position == 0 else weight / 2
        if informational and name not in _NEVER_DAMPED:
            points *= INFORMATIONAL_DAMPING
        total += points
        reasons.append(f"{name}+{round(points)}")
    if context.low_retrieval_confidence:
        total += 15
        reasons.append("low_retrieval_confidence+15")
    if context.recent_denials >= 3:
        total += 20
        reasons.append("repeated_denied_access+20")
    if context.prior_open_escalations:
        total += 10
        reasons.append("prior_open_escalation+10")
    final = min(100, round(total))
    return Score(final, level_for(final), reasons)
