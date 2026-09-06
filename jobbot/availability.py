from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

MONTHS = {
    "jan": 1, "january": 1, "ene": 1, "enero": 1,
    "feb": 2, "february": 2, "febrero": 2,
    "mar": 3, "march": 3, "marzo": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "june": 6, "junio": 6,
    "jul": 7, "july": 7, "julio": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "septiembre": 9, "setiembre": 9,
    "oct": 10, "october": 10, "octubre": 10,
    "nov": 11, "november": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dic": 12, "diciembre": 12,
}


def resolve_as_of(value: str | date | None = None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    return date.today()


def _valid_year(year: int, as_of: date) -> bool:
    # Job-board deadline years far outside the operational horizon are almost always
    # source/parser corruption (EURAXESS occasionally exposes malformed years).
    return as_of.year - 1 <= year <= as_of.year + 3


def _parse_date_token(token: str, as_of: date) -> date | None:
    s = re.sub(r"\s+", " ", token.strip().replace(",", " "))
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
    # Spanish/Catalan month dates often use "30 de Agosto de 2026".
    s = re.sub(r"\bde\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()

    # dd.mm.yyyy / dd-mm-yyyy / dd/mm/yyyy / yyyy-mm-dd
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d if _valid_year(d.year, as_of) else None
        except ValueError:
            pass

    # 25 August 2026 / August 25 2026 (English + common Spanish month names)
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+(\d{4})", s)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = MONTHS.get(mon) or MONTHS.get(mon[:3])
        if month and _valid_year(year, as_of):
            try:
                return date(year, month, day)
            except ValueError:
                return None

    m = re.fullmatch(r"([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+(\d{1,2})\s+(\d{4})", s)
    if m:
        mon, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        month = MONTHS.get(mon) or MONTHS.get(mon[:3])
        if month and _valid_year(year, as_of):
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _deadline_candidates(text: str, as_of: date) -> list[tuple[date, str]]:
    """Extract dates only from deadline/closing contexts, not arbitrary dates in a JD."""
    if not text:
        return []
    patterns = [
        # BIST / WP Job Manager board header: Closes: Sep 6, 2026
        r"\bcloses?\s*[:\-]\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{4}|[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})",
        # Application Deadline: 30 Sep 2026 - 23:59
        r"(?:application\s+deadline|application\s+deadline\s+is|closing\s+date|closing\s+deadline)\s*[:\-]?\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{4}|[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})",
        # Deadline for applications: 01/09/2026 / Deadline to apply: 06-09-2026
        r"\bdeadline(?:\s+(?:for\s+applications?|to\s+apply|for\s+submission))?\s*[:\-]\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{4}|[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})",
        # Deadline: Please submit ... by 30/09/2026 / deadline is 30 September 2026
        r"\bdeadline\b.{0,90}?(?:\b(?:by|is|until)\b|:)\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{4}|[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})",
        # How to apply: Until 31st August 2026
        r"(?:how\s+to\s+apply|applications?).{0,120}?\buntil\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{4}|[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})",
        # submit applications by / applications ... until
        r"(?:submit(?:\s+your)?\s+application|submit\s+applications?|applications?\s+(?:will\s+be\s+)?(?:accepted|received|open)|receipt\s+of\s+applications).{0,100}?\b(?:by|until|through)\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{4}|[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})",
        # Catalan/Spanish common board language.
        r"(?:termini\s+(?:de\s+recepci[oó]\s+de\s+candidatures|de\s+presentaci[oó])|fecha\s+l[ií]mite|plazo\s+de\s+presentaci[oó]n|fecha\s+fin\s+de\s+inscripci[oó]n|fin\s+del\s+plazo\s+de\s+presentaci[oó]n\s+de\s+solicitudes).{0,100}?"
        r"(?:[A-Za-zÁÉÍÓÚáéíóúñÑ]+[,]?\s+)?(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}(?:\s+de)?\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+(?:\s+de)?[,]?\s+\d{4})",
        # Spanish application window: "Plazo de solicitud del 20/07/2026 al 31/07/2026".
        r"plazo\s+de\s+solicitud.{0,80}?\b(?:al|hasta)\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}(?:\s+de)?\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+(?:\s+de)?[,]?\s+\d{4})",
        # Explicit receipt-of-applications wording used by Spanish research institutes.
        r"fecha\s+l[ií]mite\s+de\s+recepci[oó]n\s+de\s+solicitudes.{0,80}?"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}(?:\s+de)?\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+(?:\s+de)?[,]?\s+\d{4})",
    ]
    found: list[tuple[date, str]] = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.I | re.S):
            token = m.group(1)
            d = _parse_date_token(token, as_of)
            if d:
                evidence = re.sub(r"\s+", " ", m.group(0)).strip()[:180]
                found.append((d, evidence))
    # Stable unique by date + evidence.
    out: list[tuple[date, str]] = []
    seen = set()
    for item in found:
        key = (item[0].isoformat(), item[1].lower())
        if key not in seen:
            seen.add(key); out.append(item)
    return out


def assess_availability(job: dict[str, Any], as_of: str | date | None = None) -> dict[str, Any]:
    """Return availability metadata without altering fit score/recommendation.

    Explicit application deadlines outrank unreliable portal footer labels such as
    `STATUS: EXPIRED`. When several explicit deadlines conflict, the earliest plausible
    deadline is used conservatively and the conflict is surfaced for audit.
    """
    day = resolve_as_of(as_of)
    text = "\n".join(str(job.get(k) or "") for k in ("description", "full_detail"))
    candidates = _deadline_candidates(text, day)

    # Biocat's board-level `Ends:` field is stored in job['date']; it is a true closing date.
    if str(job.get("source") or "").lower().startswith("biocat"):
        board_date = _parse_date_token(str(job.get("date") or ""), day)
        if board_date:
            candidates.append((board_date, f"Biocat board Ends: {job.get('date')}"))

    # Remove duplicate dates for conflict calculation but retain one evidence string/date.
    by_date: dict[date, str] = {}
    for d, evidence in candidates:
        by_date.setdefault(d, evidence)

    until_filled = bool(re.search(
        r"(?:applications?|receipt of applications).{0,80}(?:until a candidate is selected|until the position is filled|rolling basis)|"
        r"open until (?:a )?(?:suitable )?candidate is (?:selected|found)",
        text, re.I | re.S
    ))
    explicitly_closed = bool(re.search(
        r"\bplazo\s+de\s+solicitud\s+cerrado\b|"
        r"\bestado\s*:?\s*(?:cerrado|closed|en\s+subsanaci[oó]n)\b|"
        r"\btermini(?:\s+de\s+sol[·.]licitud)?\s+tancat\b|"
        r"\bapplications?\s+closed\b",
        text, re.I | re.S
    ))

    if by_date:
        chosen = min(by_date)
        status = "OPEN" if chosen >= day else "CLOSED"
        return {
            "application_status": status,
            "application_deadline": chosen.isoformat(),
            "deadline_conflict": len(by_date) > 1,
            "deadline_candidates": [d.isoformat() for d in sorted(by_date)],
            "deadline_evidence": by_date[chosen],
            "availability_as_of": day.isoformat(),
        }
    if explicitly_closed:
        return {
            "application_status": "CLOSED",
            "application_deadline": "",
            "deadline_conflict": False,
            "deadline_candidates": [],
            "deadline_evidence": "Employer page explicitly states the application period is closed",
            "availability_as_of": day.isoformat(),
        }
    if until_filled:
        return {
            "application_status": "OPEN_UNTIL_FILLED",
            "application_deadline": "",
            "deadline_conflict": False,
            "deadline_candidates": [],
            "deadline_evidence": "Open/rolling until a candidate is selected",
            "availability_as_of": day.isoformat(),
        }

    # Madrid's public result page explicitly calls the returned records "ofertas activas".
    # That is useful evidence that the vacancy is currently listed, but it is a different
    # concept from `fcPublicacionHasta` and from an employer application deadline. Use the
    # live active-listing signal only when no explicit deadline/rolling wording was found.
    if str(job.get("source") or "").lower().startswith("madrid i+d+i") and job.get("source_listing_active") is True:
        return {
            "application_status": "OPEN",
            "application_deadline": "",
            "deadline_conflict": False,
            "deadline_candidates": [],
            "deadline_evidence": f"Listed in Madrid I+D+i active offers as of {day.isoformat()}",
            "availability_as_of": day.isoformat(),
        }
    return {
        "application_status": "UNKNOWN",
        "application_deadline": "",
        "deadline_conflict": False,
        "deadline_candidates": [],
        "deadline_evidence": "",
        "availability_as_of": day.isoformat(),
    }
