"""Text parsing: thread titles, role sections, deadlines, submission links.

Everything here is pure text -> data, so it is testable without Discord.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------------------------------------------------------------------
# Timezones
# ---------------------------------------------------------------------------

#: Abbreviations people actually type in these threads -> IANA zone.
TZ_ABBREVIATIONS: dict[str, str] = {
    "ET": "America/New_York",
    "ET/": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "AKT": "America/Anchorage",
    "HST": "Pacific/Honolulu",
    "UTC": "UTC",
    "GMT": "UTC",
    "Z": "UTC",
    "BST": "Europe/London",
    "WET": "Europe/Lisbon",
    "CET": "Europe/Berlin",
    "CEST": "Europe/Berlin",
    "EET": "Europe/Athens",
    "EEST": "Europe/Athens",
    "MSK": "Europe/Moscow",
    "IST": "Asia/Kolkata",
    "PKT": "Asia/Karachi",
    "GST": "Asia/Dubai",
    "WIB": "Asia/Jakarta",
    "SGT": "Asia/Singapore",
    "PHT": "Asia/Manila",
    "HKT": "Asia/Hong_Kong",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "AWST": "Australia/Perth",
    "NZST": "Pacific/Auckland",
    "BRT": "America/Sao_Paulo",
    "ART": "America/Argentina/Buenos_Aires",
    "SAST": "Africa/Johannesburg",
    "WAT": "Africa/Lagos",
    "EAT": "Africa/Nairobi",
}

#: Uppercase words that look like a timezone but are not one.
NOT_TIMEZONES = {"AM", "PM", "ETA", "EOD", "ASAP", "TBD", "TBA", "ON", "AT", "BY"}

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def resolve_timezone(label: str, fallback: str = "UTC") -> tuple[ZoneInfo, str]:
    """Map 'ET', 'IST' or 'America/New_York' to a ZoneInfo plus its label."""

    label = (label or "").strip().strip("()")
    if label:
        key = label.upper()
        if key in TZ_ABBREVIATIONS:
            return ZoneInfo(TZ_ABBREVIATIONS[key]), key
        try:
            return ZoneInfo(label), label
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    try:
        return ZoneInfo(fallback), fallback
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC"), "UTC"


def zone_name(label: str, fallback: str = "UTC") -> str:
    """The IANA name a label resolves to ('ET' -> 'America/New_York')."""

    key = (label or "").strip().strip("()").upper()
    if key in TZ_ABBREVIATIONS:
        return TZ_ABBREVIATIONS[key]
    tz, _ = resolve_timezone(label, fallback)
    return str(tz)


# ---------------------------------------------------------------------------
# Thread titles:  09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?
# ---------------------------------------------------------------------------

_TITLE_DATE = r"(?P<date>\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4})"

#: Preferred shape: "09-25-26 | VIDEO-001 | Title".
RE_THREAD_TITLE = re.compile(
    r"^\s*" + _TITLE_DATE + r"\s*\|\s*"
    r"(?P<slot>[A-Za-z0-9 _\-#]{1,32}?)\s*\|\s*(?P<title>.+?)\s*$"
)

#: Same shape with dashes as separators. Tried second so a slot like
#: "VIDEO-001" is not split on its own hyphen.
RE_THREAD_TITLE_LOOSE = re.compile(
    r"^\s*" + _TITLE_DATE + r"\s*[\u2013\u2014-]\s*"
    r"(?P<slot>[A-Za-z0-9 _#]{1,32}?)\s*[\u2013\u2014-]\s*(?P<title>.+?)\s*$"
)

#: "09-25-26 | Title" with no slot id.
RE_THREAD_TITLE_DATE_ONLY = re.compile(
    r"^\s*" + _TITLE_DATE + r"\s*[|\u2013\u2014-]\s*(?P<title>.+?)\s*$"
)


@dataclass
class TitleInfo:
    raw: str = ""
    slate_date: Optional[datetime] = None
    slot: str = ""
    title: str = ""


def parse_thread_title(name: str, date_order: str = "MDY") -> TitleInfo:
    """Split the thread name into its slate date, slot id and title."""

    name = (name or "").strip()
    info = TitleInfo(raw=name, title=name)
    match = RE_THREAD_TITLE.match(name) or RE_THREAD_TITLE_LOOSE.match(name)
    if not match:
        date_only = RE_THREAD_TITLE_DATE_ONLY.match(name)
        if date_only:
            info.title = date_only.group("title").strip()
            info.slate_date = parse_date_token(
                date_only.group("date"), date_order=date_order
            )
            return info
        # Fall back to "<slot> | <title>" or the bare name.
        parts = [p.strip() for p in re.split(r"\s*\|\s*", name) if p.strip()]
        if len(parts) >= 2 and re.match(r"^[A-Za-z]+[- ]?\d+$", parts[0]):
            info.slot = parts[0].upper()
            info.title = " | ".join(parts[1:])
        return info

    info.slot = re.sub(r"\s+", "-", match.group("slot").strip()).upper()
    info.title = match.group("title").strip()
    found = parse_date_token(match.group("date"), date_order=date_order)
    if found:
        info.slate_date = found
    return info


def parse_date_token(token: str, date_order: str = "MDY") -> Optional[datetime]:
    """Parse a bare '09-25-26' / '2026-09-25' date into a midnight-UTC date."""

    parts = re.split(r"[-/.]", token.strip())
    if len(parts) != 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts[0]) == 4:
        year, month, day = nums
    else:
        first, second, third = nums
        if date_order.upper().startswith("D") or first > 12 >= second:
            day, month = first, second
        else:
            month, day = first, second
        year = _expand_year(third)
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _expand_year(year: int) -> int:
    if year >= 1000:
        return year
    return 2000 + year if year < 70 else 1900 + year


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------


@dataclass
class FoundTime:
    """One date/time found in free text."""

    dt: datetime                 # timezone-aware, normalised to UTC
    raw: str
    tz_label: str = ""
    zone: str = ""
    had_time: bool = False
    exact: bool = False          # true for Discord <t:...> timestamps

    @property
    def is_utc_only(self) -> bool:
        return not self.tz_label


RE_DISCORD_TS = re.compile(r"<t:(?P<epoch>\d{6,})(?::[tTdDfFR])?>")

_TIME = (
    r"(?:\s*(?:@|at|,|-|–)?\s*"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?::\d{2})?\s*"
    r"(?P<ampm>[AaPp]\.?[Mm]\.?)?"
    r"(?:\s*\(?(?P<tz>[A-Za-z]{2,5}|[A-Za-z]+/[A-Za-z_]+)\)?)?"
    r")?"
)

RE_NUMERIC_DATE = re.compile(
    r"(?<![\d/\-])(?P<first>\d{1,2})[/\-.](?P<second>\d{1,2})[/\-.](?P<year>\d{2,4})(?![\d])"
    + _TIME
)

RE_ISO_DATE = re.compile(
    r"(?<![\d])(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?:T|\s)?" + _TIME
)

RE_MONTH_NAME = re.compile(
    r"(?<![A-Za-z])(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?" + _TIME,
    re.IGNORECASE,
)


def _clean_tz(token: Optional[str]) -> str:
    if not token:
        return ""
    key = token.strip().strip("()")
    if key.upper() in NOT_TIMEZONES:
        return ""
    if key.upper() in TZ_ABBREVIATIONS or "/" in key:
        return key
    return ""


def _build(
    year: int,
    month: int,
    day: int,
    match: re.Match,
    default_tz: str,
    assume_time: time,
) -> Optional[FoundTime]:
    hour_txt = match.groupdict().get("hour")
    minute_txt = match.groupdict().get("minute")
    ampm = (match.groupdict().get("ampm") or "").replace(".", "").upper()
    tz_label = _clean_tz(match.groupdict().get("tz"))

    had_time = hour_txt is not None
    if had_time:
        hour = int(hour_txt)
        minute = int(minute_txt or 0)
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
    else:
        hour, minute = assume_time.hour, assume_time.minute

    tz, label = resolve_timezone(tz_label or default_tz, default_tz)
    try:
        local = datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError:
        return None
    return FoundTime(
        dt=local.astimezone(timezone.utc),
        raw=match.group(0).strip(),
        tz_label=tz_label or "",
        zone=str(tz),
        had_time=had_time,
    )


def extract_datetimes(
    text: str,
    default_tz: str = "UTC",
    assume_time: time = time(23, 59),
    date_order: str = "MDY",
) -> list[FoundTime]:
    """Find every date/time in ``text``, in the order they appear."""

    if not text:
        return []
    found: list[FoundTime] = []
    consumed: list[tuple[int, int]] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in consumed)

    for match in RE_DISCORD_TS.finditer(text):
        consumed.append(match.span())
        found.append(
            FoundTime(
                dt=datetime.fromtimestamp(int(match.group("epoch")), tz=timezone.utc),
                raw=match.group(0),
                tz_label="UTC",
                zone="UTC",
                had_time=True,
                exact=True,
            )
        )

    for match in RE_ISO_DATE.finditer(text):
        if overlaps(match.span()):
            continue
        item = _build(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            match,
            default_tz,
            assume_time,
        )
        if item:
            consumed.append(match.span())
            found.append(item)

    for match in RE_NUMERIC_DATE.finditer(text):
        if overlaps(match.span()):
            continue
        first, second = int(match.group("first")), int(match.group("second"))
        if date_order.upper().startswith("D") or first > 12 >= second:
            day, month = first, second
        else:
            month, day = first, second
        item = _build(
            _expand_year(int(match.group("year"))),
            month,
            day,
            match,
            default_tz,
            assume_time,
        )
        if item:
            consumed.append(match.span())
            found.append(item)

    for match in RE_MONTH_NAME.finditer(text):
        if overlaps(match.span()):
            continue
        year = int(match.group("year")) if match.group("year") else datetime.now(timezone.utc).year
        item = _build(
            year,
            MONTHS[match.group("mon")[:4].upper().rstrip(".") if match.group("mon")[:4].upper() == "SEPT" else match.group("mon")[:3].upper()],
            int(match.group("day")),
            match,
            default_tz,
            assume_time,
        )
        if item:
            consumed.append(match.span())
            found.append(item)

    found.sort(key=lambda f: text.find(f.raw) if f.raw in text else 0)
    return found


def choose_deadline(
    candidates: Iterable[FoundTime], preferred_zones: Iterable[str] = ()
) -> Optional[FoundTime]:
    """Pick the deadline to trust when a post lists several timezones.

    These briefs list the same moment twice (US then IST). They should agree,
    so preference only decides which spelling we quote back; an exact Discord
    timestamp always wins, and otherwise the earliest moment is the safe one.
    """

    items = list(candidates)
    if not items:
        return None
    for item in items:
        if item.exact:
            return item
    wanted = [zone_name(z) for z in preferred_zones]
    for zone in wanted:
        for item in items:
            if item.zone == zone and item.tz_label:
                return item
    with_tz = [i for i in items if i.tz_label]
    pool = with_tz or items
    return min(pool, key=lambda i: i.dt)


# ---------------------------------------------------------------------------
# Role sections inside the opening post
# ---------------------------------------------------------------------------

DEFAULT_ROLES = [
    "SCRIPT", "SCRIPTWRITER", "SCRIPT WRITER", "WRITING",
    "VOICE OVER", "VOICEOVER", "VO", "NARRATION",
    "THUMBNAIL", "THUMBNAILS", "ART", "ARTIST",
    "EDIT", "EDITOR", "EDITING", "VIDEO EDIT",
    "RESEARCH", "SEO", "UPLOAD", "PUBLISH", "REVIEW",
]

RE_USER_MENTION = re.compile(r"<@!?(?P<id>\d{5,})>")
RE_AT_NAME = re.compile(r"@([A-Za-z0-9._\- ]{2,32}?)(?=$|[\s,;:|)\]]|$)")
RE_WORD_COUNT = re.compile(
    r"(?:word\s*count|words?|length)\s*[:\-–]?\s*"
    r"(?P<count>\d{1,3}(?:[,.]\d{3})+|\d{3,6})\s*(?:\+|k\b)?",
    re.IGNORECASE,
)
RE_WORD_COUNT_TRAILING = re.compile(
    r"(?P<count>\d{1,3}(?:,\d{3})+|\d{3,6})\s*(?:\+)?\s*words\b", re.IGNORECASE
)
RE_DEADLINE_LABEL = re.compile(r"(?:dead\s*line|due(?:\s*date)?|delivery)\s*[:\-–]?", re.IGNORECASE)
RE_NEXT_KEY = re.compile(
    r"^\s*[•◦▪\-*>]*\s*"
    r"(word\s*count|length|story\s*brief|brief|notes?|references?|format|tone|"
    r"requirements?|payment|rate|status|links?|resources?)\b",
    re.IGNORECASE,
)


@dataclass
class RoleSection:
    role: str = ""
    header: str = ""
    body: str = ""
    mention_ids: list[str] = field(default_factory=list)
    mention_names: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return f"{self.header}\n{self.body}"


def _normalise_role(token: str) -> str:
    token = re.sub(r"\s+", " ", token.strip().upper())
    aliases = {
        "SCRIPTWRITER": "SCRIPT",
        "SCRIPT WRITER": "SCRIPT",
        "WRITING": "SCRIPT",
        "VOICEOVER": "VOICE OVER",
        "NARRATION": "VOICE OVER",
        "THUMBNAILS": "THUMBNAIL",
        "ARTIST": "ART",
        "EDITOR": "EDIT",
        "EDITING": "EDIT",
        "VIDEO EDIT": "EDIT",
    }
    return aliases.get(token, token)


def _role_in_line(line: str, roles: Iterable[str]) -> Optional[str]:
    """Return the role a header line announces, if it is a header line."""

    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None
    # Bulleted lines are section content, not headers.
    if re.match(r"^\s*[•◦▪]", line):
        return None
    for role in sorted(roles, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z]){re.escape(role)}(?![A-Za-z])", stripped):
            # Headers shout; body prose mentioning "script" does not.
            return _normalise_role(role)
    return None


def mentions(text: str) -> tuple[list[str], list[str]]:
    """Return (user ids, plain @names) mentioned in ``text``."""

    ids = [m.group("id") for m in RE_USER_MENTION.finditer(text or "")]
    without_ids = RE_USER_MENTION.sub(" ", text or "")
    names = [m.group(1).strip() for m in RE_AT_NAME.finditer(without_ids)]
    return ids, [n for n in names if n]


def split_role_sections(body: str, roles: Iterable[str] = DEFAULT_ROLES) -> list[RoleSection]:
    """Split an opening post into its per-role sections."""

    lines = (body or "").splitlines()
    sections: list[RoleSection] = []
    current: Optional[RoleSection] = None
    buffer: list[str] = []

    for line in lines:
        role = _role_in_line(line, roles)
        if role:
            if current:
                current.body = "\n".join(buffer).strip()
                sections.append(current)
            ids, names = mentions(line)
            current = RoleSection(role=role, header=line.strip(), mention_ids=ids, mention_names=names)
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current:
        current.body = "\n".join(buffer).strip()
        sections.append(current)

    # A section's assignee is sometimes on the line below the header.
    for section in sections:
        if not section.mention_ids and not section.mention_names:
            head = "\n".join(section.body.splitlines()[:2])
            ids, names = mentions(head)
            section.mention_ids, section.mention_names = ids, names
    return sections


def deadline_text(section_text: str) -> str:
    """Narrow a section down to the lines that state its deadline."""

    lines = section_text.splitlines()
    for index, line in enumerate(lines):
        if RE_DEADLINE_LABEL.search(line):
            chunk = [line]
            for following in lines[index + 1:]:
                if RE_NEXT_KEY.match(following):
                    break
                if RE_DEADLINE_LABEL.search(following) and chunk[1:]:
                    break
                chunk.append(following)
                if len(chunk) > 8:
                    break
            return "\n".join(chunk)
    return ""


def parse_word_count(text: str) -> Optional[int]:
    for regex in (RE_WORD_COUNT, RE_WORD_COUNT_TRAILING):
        match = regex.search(text or "")
        if match:
            raw = match.group("count").replace(",", "").replace(".", "")
            try:
                value = int(raw)
            except ValueError:
                continue
            if match.group(0).rstrip().lower().endswith("k"):
                value *= 1000
            if 100 <= value <= 200000:
                return value
    return None


# ---------------------------------------------------------------------------
# Submission links
# ---------------------------------------------------------------------------

RE_URL = re.compile(r"https?://[^\s<>()\[\]\"']+", re.IGNORECASE)

DEFAULT_LINK_PATTERNS = [r"drive\.google\.com", r"docs\.google\.com"]


def find_links(text: str, patterns: Iterable[str] = DEFAULT_LINK_PATTERNS) -> list[str]:
    """URLs in ``text`` matching any submission-link pattern."""

    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    hits: list[str] = []
    for match in RE_URL.finditer(text or ""):
        url = match.group(0).rstrip(".,;:!?)")
        if any(c.search(url) for c in compiled) and url not in hits:
            hits.append(url)
    return hits
