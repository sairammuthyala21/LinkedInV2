"""Classify LinkedIn contract listings for a staffing agency.

LinkedIn's ``Contract`` employment type does not say whether a role accepts
W-2 employees, corp-to-corp submissions, or independent contractors. The
classifier uses the posting text and preserves uncertain jobs for review.
"""

import re
from typing import NamedTuple


class ContractAssessment(NamedTuple):
    status: str  # "keep", "review", or "skip"
    reason: str


_C2C = re.compile(
    r"\b(?:c\s*[-/]?\s*2\s*[-/]?\s*c|"
    r"corp(?:oration)?[\s-]*to[\s-]*corp(?:oration)?)\b",
    re.IGNORECASE,
)
_W2 = re.compile(r"\bw\s*[-/]?\s*2\b", re.IGNORECASE)
_INDEPENDENT = re.compile(
    r"\b(?:1099|independent\s+contractor|self[- ]employed)\b",
    re.IGNORECASE,
)
_NEGATIVE_PREFIX = re.compile(
    r"\b(?:no|not|without|excluding|except|cannot|can't|unable to|"
    r"do not|don't|will not|won't)\b[\w\s/-]{0,45}$",
    re.IGNORECASE,
)
_NEGATIVE_SUFFIX = re.compile(
    r"^\s*(?:(?:or|and|/)\s*(?:c2c|1099|independent contractor)\s*)?"
    r"(?:(?:is|are|will be)\s+)?(?:not|never)\s+"
    r"(?:accepted|allowed|available|considered|eligible|permitted|supported)\b",
    re.IGNORECASE,
)
_NO_AGENCIES = re.compile(
    r"\b(?:no|not accepting|not considering|not able to consider|"
    r"do not accept|don't accept|cannot accept|can't accept|won't accept)\s+"
    r"(?:staffing\s+)?"
    r"(?:agencies|agency|third[- ]party|third[- ]parties|vendors|subcontractors)\b"
    r"|\b(?:agencies|agency|third[- ]party|third[- ]parties|vendors)\s+"
    r"(?:(?:submissions|candidates)\s+)?(?:are\s+)?not\s+"
    r"(?:accepted|allowed|considered|permitted)\b",
    re.IGNORECASE,
)
_W2_ONLY = re.compile(
    r"\bw2\s+(?:only|candidates\s+only|employees\s+only|required)\b"
    r"|\bonly\s+(?:on\s+)?(?:our\s+)?w2\b"
    r"|\bmust\s+(?:be\s+)?(?:on\s+)?(?:our\s+)?w2\b",
    re.IGNORECASE,
)
_W2_ROLE = re.compile(
    r"\b(?:contract|employment|engagement|payroll|pay)\s+type\s*:\s*w2\b"
    r"|\bw2\s+(?:contract|role|position|engagement|candidate)\b"
    r"|\b(?:on|via|through)\s+(?:our\s+)?w2\b"
    r"|\b(?:pay|rate|hourly|per\s+hour)\b[^\n.;]{0,60}\bw2\b"
    r"|\bw2\b[^\n.;]{0,20}\b(?:rate|pay|hourly)\b",
    re.IGNORECASE,
)
_CTC = re.compile(r"\bctc\b", re.IGNORECASE)


def _mentions(text: str, pattern: re.Pattern) -> tuple[bool, bool]:
    """Return whether a term is positively mentioned and/or rejected."""
    positive = negative = False
    for match in pattern.finditer(text):
        preceding = re.split(r"[.!?;\n]", text[max(0, match.start() - 65):match.start()])[-1]
        following = text[match.end():match.end() + 45]
        if _NEGATIVE_PREFIX.search(preceding) or _NEGATIVE_SUFFIX.search(following):
            negative = True
        else:
            positive = True
    return positive, negative


def classify_contract_job(job: dict) -> ContractAssessment:
    """Keep clear agency-friendly jobs, review unknown ones, skip clear W-2 jobs."""
    text = f"{job.get('title') or ''}\n{job.get('description') or ''}"
    text = re.sub(r"[*_~\\]", " ", text).translate(str.maketrans("–—", "--"))
    text = _C2C.sub("c2c", text)
    text = _W2.sub("w2", text)

    c2c, no_c2c = _mentions(text, re.compile(r"\bc2c\b", re.IGNORECASE))
    independent, no_independent = _mentions(text, _INDEPENDENT)

    if _NO_AGENCIES.search(text):
        return ContractAssessment("skip", "Posting rejects agencies or third parties")

    if _W2_ONLY.search(text):
        if c2c or independent:
            return ContractAssessment("review", "Conflicting W-2-only and non-W-2 terms")
        return ContractAssessment("skip", "W-2 only")

    if c2c and no_c2c:
        return ContractAssessment("review", "Conflicting C2C terms")
    if independent and no_independent:
        return ContractAssessment("review", "Conflicting independent-contractor terms")
    if c2c:
        return ContractAssessment("keep", "C2C accepted or offered")
    if independent:
        return ContractAssessment("keep", "1099 or independent contractor offered")

    if _CTC.search(text):
        return ContractAssessment("review", "CTC wording is ambiguous")
    if _W2_ROLE.search(text):
        return ContractAssessment("skip", "W-2 is the only stated arrangement")
    if no_c2c:
        return ContractAssessment("skip", "C2C rejected; no non-W-2 option stated")
    if no_independent:
        return ContractAssessment("review", "1099 rejected; C2C status unknown")
    return ContractAssessment("review", "Payment arrangement not stated")
