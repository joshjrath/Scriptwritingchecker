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


# ---------------------------------------------------------------------------
# Deadline changes negotiated in the thread
# ---------------------------------------------------------------------------

#: Phrases that mean a schedule change on their own.
RE_CHANGE_STRONG = re.compile(
    r"\b(?:new\s+deadline|deadline\s+(?:is\s+now|changed|moved|pushed|extended)|"
    r"exten(?:d|ded|ding|sion)|resched\w*|more\s+time|"
    r"(?:take|taking|have|had|giving\s+you|give\s+you)\s+(?:an?\s+|a\s+few\s+)?"
    r"(?:extra|another|couple\s+(?:more\s+)?(?:of\s+)?)?\s*(?:day|days|hours?|week))\b",
    re.IGNORECASE,
)

#: Phrases that only mean a schedule change next to a date or a weekday.
RE_CHANGE_WEAK = re.compile(
    r"\b(?:mov(?:e|ed|ing)|push(?:ed|ing)?|bump(?:ed|ing)?|slip(?:ped|ping)?)\s+"
    r"(?:it|this|that|the\s+deadline|things)?\s*(?:back|to|up|until|till)\b",
    re.IGNORECASE,
)

RE_WEEKDAY = re.compile(
    r"\b(?:mon|tues?|wed(?:nes)?|thur?s?|fri|sat(?:ur)?|sun)(?:day)?\b", re.IGNORECASE
)

RE_DEADLINE_WORD = re.compile(r"\b(?:deadline|due|extension)\b", re.IGNORECASE)

#: "9/25" - too loose for deadline parsing, but fine as corroboration here.
RE_SHORT_DATE = re.compile(r"(?<!\d)\d{1,2}[/-]\d{1,2}(?!\d)")


def looks_like_deadline_change(text: str) -> bool:
    """Does this message read like the deadline was renegotiated?

    Deliberately advisory: the brief stays the source of truth and this only
    raises a flag, because acting on a guess about a schedule change would be
    worse than telling someone to go read the thread.
    """

    text = text or ""
    if RE_CHANGE_STRONG.search(text):
        return True
    if not RE_CHANGE_WEAK.search(text):
        return False
    return bool(
        RE_WEEKDAY.search(text)
        or RE_DEADLINE_WORD.search(text)
        or RE_SHORT_DATE.search(text)
        or extract_datetimes(text)
    )


#: A shouted word or two, the way a role header is written.
RE_CAPS_TOKEN = re.compile(r"(?<![A-Za-z])([A-Z][A-Z]{2,}(?:\s+[A-Z]{2,}){0,2})(?![a-z])")


def discover_role_headers(body: str) -> list[str]:
    """Header-shaped lines in a post, whatever they are called.

    `split_role_sections` can only find roles it was told about, so it can
    never reveal a brief that says WRITER where the config says SCRIPT. This
    looks for the shape instead - a shouted label on a short line that also
    names somebody - so an unknown role shows up in the audit rather than
    silently dropping the assignment.
    """

    found: list[str] = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        if re.match(r"^\s*[\u2022\u25e6\u25aa]", line):
            continue
        ids, names = mentions(stripped)
        if not ids and not names:
            continue
        for match in RE_CAPS_TOKEN.finditer(RE_USER_MENTION.sub(" ", stripped)):
            token = re.sub(r"\s+", " ", match.group(1).strip())
            # "@ UTDR" is a mention, not a role: skip a shout that IS the name.
            if any(token.lower() == n.strip().lower() for n in names):
                continue
            if token not in found:
                found.append(token)
    return found


# ---------------------------------------------------------------------------
# Which show a brief belongs to
# ---------------------------------------------------------------------------

RE_PROJECT_LABEL = re.compile(
    r"^[^\w]*\s*(?:project|show|channel|series|client)\s*[:\-\u2013]?\s*(?P<value>.*)$",
    re.IGNORECASE,
)

#: A line that is only a handle, e.g. "@ UTDR" or "\U0001f4fa @ UTDR" - how
#: these briefs tag the show. The space after @ is required on purpose: it is
#: what separates a show tag from a mention like "@Josh", which is a person.
RE_SHOW_TAG = re.compile(
    r"^[^\w@]*@\s+(?P<value>[A-Za-z0-9][A-Za-z0-9 _.\-]{0,30})\s*$"
)

#: Values that mean "not filled in yet".
PLACEHOLDERS = {"tbd", "tba", "n/a", "na", "none", "-", "--", "?", "xxx"}


def parse_project(body: str) -> str:
    """The show a brief belongs to.

    Video numbers restart per channel, so they identify nothing on their own;
    the project is what tells two VIDEO-001s apart.
    """

    lines = (body or "").splitlines()
    labelled = ""
    tagged = ""

    for index, line in enumerate(lines):
        if not tagged:
            tag = RE_SHOW_TAG.match(line)
            if tag:
                candidate = tag.group("value").strip()
                if candidate.lower() not in PLACEHOLDERS:
                    tagged = candidate

        if labelled:
            continue
        match = RE_PROJECT_LABEL.match(line.strip())
        if not match:
            continue
        value = match.group("value").strip()
        if not value:
            # The label sits on its own line; the value is the next one.
            for following in lines[index + 1: index + 3]:
                following = following.strip()
                if following:
                    value = following
                    break
        value = value.strip("*_` ").strip()
        if value and value.lower() not in PLACEHOLDERS and len(value) <= 40:
            labelled = value

    return labelled or tagged
