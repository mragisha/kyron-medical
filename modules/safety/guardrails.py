"""
guardrails.py — Kyron Medical Safety / Guardrails Library

Heuristic keyword/pattern matching. No LLM calls. No external APIs.
"""

import re
from typing import List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAFE_REDIRECT = (
    "I'm not able to provide medical advice. "
    "Please consult your doctor or call our office directly."
)

# Phrases that indicate the AI is giving medical advice or a diagnosis.
# Patterns are matched case-insensitively against the full text.
_MEDICAL_ADVICE_PATTERNS: List[str] = [
    # Explicit treatment / medication recommendations
    r"you should take\b",
    r"i recommend (you )?(take|use|try|start|stop|avoid)\b",
    r"you (need|must|should|ought to) (take|use|start|stop|avoid)\b",
    r"\bprescribe\b",
    r"\bprescription\b",
    r"\bdosage\b",
    r"\bdose of\b",
    r"\d+\s*mg\b",
    r"\d+\s*(ml|tablet|pill|capsule)\b",
    r"\bmg (every|per|a day|daily|twice|three times)\b",
    r"take \d+\s*(mg|ml|tablet|pill|capsule)",
    r"\btreatment for your\b",
    r"\btreat your\b",
    r"\bcure\b",
    r"\bmedication for your\b",
    r"\btake this (drug|medicine|medication|pill|tablet)\b",
    # Diagnosis language
    r"your diagnosis\b",
    r"you have (been diagnosed|diabetes|cancer|hypertension|asthma|"
    r"depression|anxiety|infection|disorder|disease|condition|syndrome|"
    r"deficiency|allergy|virus|bacteria|tumou?r|fracture|arthritis|"
    r"pneumonia|covid|flu|fever|ulcer)\b",
    r"you are (suffering|experiencing) from\b",
    r"you are (suffering|experiencing|diagnosed)\b",
    r"symptoms indicate (that )?(you have|a diagnosis|the presence)\b",
    r"based on (your )?symptoms (you have|this is|you are|it (looks|seems|appears))\b",
    r"sounds like you (have|are suffering|may have)\b",
    r"you (likely|probably|definitely|certainly) have\b",
    r"this (appears|looks|seems) to be (a |an )?(diagnosis|condition|disease|disorder)\b",
    r"\bdiagnose\b",
    r"\bdiagnosis\b",
    r"\bprognosis\b",
    # Specific drug / dosage instructions
    r"\bibuprofen\b",
    r"\baspirin\b",
    r"\bparacetamol\b",
    r"\bacetaminophen\b",
    r"\btylenol\b",
    r"\bamoxicillin\b",
    r"\bantibiotic\b",
    r"\bsteroid\b",
    r"\binsulin\b",
    r"\bblood pressure medication\b",
    r"\bcholesterol medication\b",
    r"\bantidepressant\b",
    r"\bsedative\b",
    r"\bpainkillers?\b",
    r"\bopioid\b",
    r"\bnarcotics?\b",
    # Self-harm / crisis (must be caught and redirected)
    r"\bsuicid(e|al|ally)\b",
    r"\bself.?harm\b",
    r"\bend(ing)? (my|their|his|her) life\b",
    r"\bkill (my|him|her|them)self\b",
    r"\bcut (my|him|her|them)self\b",
    r"\boverdos(e|ing)\b",
    # Drug interactions
    r"\bdrug interaction\b",
    r"\binteracts? with\b",
    r"\bcombine (these )?medications\b",
    r"\bmix (these )?medications\b",
    r"\btake .+ (with|and) .+ (together|simultaneously)\b",
]

# Compile once for performance
_COMPILED_MEDICAL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _MEDICAL_ADVICE_PATTERNS
]

# Out-of-scope topics: things the Kyron Medical patient portal cannot help with.
_OUT_OF_SCOPE_PATTERNS: List[str] = [
    # Legal
    r"\blegal advice\b",
    r"\blawsuit\b",
    r"\bsue (my|the|a|an)\b",
    r"\battorney\b",
    r"\blawyer\b",
    r"\blitigation\b",
    r"\bmedical malpractice\b",
    r"\bpersonal injury\b",
    r"\bworkers.?comp\b",
    # Financial / insurance billing disputes (deeper than simple billing Q)
    r"\bfinancial advice\b",
    r"\bstock (market|tips|picks|portfolio)\b",
    r"\binvest(ment|ing|or)\b",
    r"\bcryptocurrency\b",
    r"\btax(es|return|filing|advice)\b",
    r"\baccountant\b",
    r"\bbank(ing|account|loan)\b",
    # Unrelated specialties / pet care this portal does not serve
    r"\bveterinar(y|ian)\b",
    r"\bpet (health|medicine|treatment)\b",
    r"\banimal (health|care|doctor)\b",
    r"\b(my )?(dog|cat|horse|rabbit|hamster|bird|fish|reptile) (has|is|was|have)\b",
    r"\b(dog|cat|horse|rabbit|hamster|bird|reptile) health\b",
    # Completely off-topic
    r"\bweather forecast\b",
    r"\bsports (score|team|game|bet)\b",
    r"\breal estate\b",
    r"\bhoroscope\b",
    r"\brecipe\b",
    r"\bcooking\b",
    r"\btravel (tips|plan|booking)\b",
    r"\bflight\b",
    r"\bhotel\b",
    r"\bbook (a flight|a hotel|a trip)\b",
    r"\bsocial media\b",
    r"\bpolitics\b",
    r"\belection\b",
    r"\bnews\b",
    r"\bsports?\b",
    r"\bgambling\b",
    r"\bcasino\b",
    r"\blottery\b",
]

_COMPILED_OOS_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _OUT_OF_SCOPE_PATTERNS
]

# Topics the portal explicitly does handle — used to override false positives
# in out-of-scope detection.
_IN_SCOPE_PATTERNS: List[str] = [
    r"\bappointment\b",
    r"\bschedule\b",
    r"\bdoctor\b",
    r"\bspecialist\b",
    r"\bcardiolog(y|ist)\b",
    r"\borthoped(ics|ist)\b",
    r"\bpediatr(ics|ician)\b",
    r"\bdermatolog(y|ist)\b",
    r"\bneurol(ogy|ogist)\b",
    r"\bendocrinolog(y|ist)\b",
    r"\bpsychiatr(y|ist)\b",
    r"\bgynecolog(y|ist)\b",
    r"\burgent care\b",
    r"\bprimary care\b",
    r"\brefill\b",
    r"\bprescription refill\b",
    r"\boffice hours\b",
    r"\bcontact\b",
    r"\baddress\b",
    r"\blocation\b",
    r"\binsurance\b",
    r"\bbilling\b",
    r"\bco.?pay\b",
]

_COMPILED_IN_SCOPE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _IN_SCOPE_PATTERNS
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_medical_advice(text: str) -> bool:
    """
    Return True if text appears to contain medical advice, diagnosis,
    drug dosage instructions, self-harm content, or dangerous drug interaction
    information.
    """
    if not text or not text.strip():
        return False
    for pattern in _COMPILED_MEDICAL_PATTERNS:
        if pattern.search(text):
            return True
    return False


def sanitize_response(text: str) -> str:
    """
    If text contains medical advice/diagnosis language, replace the entire
    response with a safe redirect message.
    Otherwise return text unchanged.
    """
    if is_medical_advice(text):
        return SAFE_REDIRECT
    return text


def check_out_of_scope(text: str) -> bool:
    """
    Return True if the patient message is clearly outside the practice scope.

    A message is considered in-scope if it matches any in-scope pattern,
    even if it also matches an out-of-scope pattern (e.g. "I need to see a
    cardiologist" contains the word "see" which is not a flag, but mentions
    a specialty the portal handles).
    """
    if not text or not text.strip():
        return False

    # If the message is clearly about portal-handled topics, never flag it.
    for pattern in _COMPILED_IN_SCOPE_PATTERNS:
        if pattern.search(text):
            return False

    # Otherwise check for out-of-scope triggers.
    for pattern in _COMPILED_OOS_PATTERNS:
        if pattern.search(text):
            return True

    return False
