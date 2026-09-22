"""Turn raw threads into assignments with a status."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .config import Config
from . import overrides as overrides_mod
from .models import (
    Assignment,
    Confidence,
    Message,
    Status,
    Submission,
    Thread,
    sort_assignments,
)
from .parsing import (
    RoleSection,
    choose_deadline,
    deadline_text,
    extract_datetimes,
    find_links,
    looks_like_deadline_change,
    mentions,
    parse_project,
    parse_thread_title,
    parse_word_count,
    split_role_sections,
)


def _is_me(message: Message, config: Config) -> bool:
    if config.my_user_ids and message.author.id:
        if str(message.author.id) in {str(u) for u in config.my_user_ids}:
            return True
    wanted = {n.strip().lower() for n in config.my_names if n.strip()}
    return any(n.strip().lower() in wanted for n in message.author.names)


def _section_is_mine(section: RoleSection, config: Config) -> Optional[bool]:
    """True / False / None when the assignee cannot be resolved.

    Returning None matters: a brief that mentions ``<@123>`` tells us nothing
    either way if no user IDs are configured, and guessing "not mine" there
    would silently hide real work.
    """

    my_ids = {str(u) for u in config.my_user_ids}
    if my_ids and section.mention_ids:
        if set(map(str, section.mention_ids)) & my_ids:
            return True
    wanted = {n.strip().lower() for n in config.my_names if n.strip()}
    if any(n.strip().lower() in wanted for n in section.mention_names):
        return True
    if section.mention_names:
        return False  # a name is given and it is not one of mine
    if section.mention_ids:
        return False if my_ids else None
    return None  # nobody named at all


def _matched_by_id(section: RoleSection, config: Config) -> bool:
    my_ids = {str(u) for u in config.my_user_ids}
    return bool(my_ids and set(map(str, section.mention_ids)) & my_ids)


def _pick_section(sections: list[RoleSection], config: Config) -> tuple[Optional[RoleSection], Optional[bool]]:
    """Choose the section for one of my roles; report whether it is mine."""

    my_roles = {r.strip().upper() for r in config.my_roles}
    candidates = [s for s in sections if s.role in my_roles]
    if not candidates:
        return None, None
    for section in candidates:
        if _section_is_mine(section, config) is True:
            return section, True
    for section in candidates:
        if _section_is_mine(section, config) is None:
            return section, None
    return candidates[0], False


def _lower(assignment: Assignment, level: Confidence) -> None:
    """Confidence only ever moves down."""

    if level.rank > assignment.confidence.rank:
        assignment.confidence = level


def _without_title_line(body: str, thread_name: str) -> str:
    """Drop the echoed title line so its slate date is not read as a deadline."""

    name = (thread_name or "").strip()
    if not name:
        return body
    return "\n".join(
        line for line in (body or "").splitlines() if line.strip() != name
    )

def build_assignment(thread: Thread, config: Config, now: Optional[datetime] = None) -> Assignment:
    now = now or datetime.now(timezone.utc)
    title_info = parse_thread_title(thread.name, date_order=config.date_order)

    assignment = Assignment(
        thread_id=thread.id,
        thread_name=thread.name,
        channel=thread.parent_name,
        guild=thread.guild_name,
        jump_url=thread.jump_url,
        slate_date=title_info.slate_date,
        slot=title_info.slot,
        title=title_info.title,
        tags=list(thread.tags),
        archived=thread.archived,
    )

    opening = thread.opening_post
    body = opening.content if opening else ""
    assignment.brief_text = body
    assignment.project = parse_project(body)
    assignment.assigned_at = (opening.created_at if opening else None) or thread.created_at
    sections = split_role_sections(body, config.known_roles)
    section, mine = _pick_section(sections, config)

    if section is not None:
        assignment.role = section.role
        assignment.assignee_text = ", ".join(
            section.mention_names + [f"<@{i}>" for i in section.mention_ids]
        )
    scope_text = section.text if section is not None else _without_title_line(body, thread.name)

    if section is not None and mine is True:
        assignment.evidence["assignee"] = (
            "user ID in the " + section.role + " section"
            if _matched_by_id(section, config)
            else "display name in the " + section.role + " section"
        )
        if not _matched_by_id(section, config):
            _lower(assignment, Confidence.MEDIUM)
    elif section is not None:
        assignment.evidence["assignee"] = "unresolved - " + (
            section.header.strip() or "no mention in the section header"
        )
        _lower(assignment, Confidence.MEDIUM)

    same_role = [s for s in sections if s.role == (section.role if section else None)]
    if len(same_role) > 1:
        assignment.warnings.append(
            f"! The opening post has {len(same_role)} {section.role} sections; "
            "the first one naming me was used."
        )
        _lower(assignment, Confidence.LOW)

    # --- deadline -----------------------------------------------------------
    labelled = deadline_text(scope_text)
    focus = labelled or (scope_text if section is not None else "")
    if section is None and body:
        # No role section at all: fall back to the whole post, but say so.
        focus = focus or _without_title_line(body, thread.name)
    candidates = extract_datetimes(
        focus,
        default_tz=config.default_timezone,
        assume_time=config.assume_time_obj,
        date_order=config.date_order,
    )
    chosen = choose_deadline(candidates, config.preferred_timezones)
    if chosen:
        assignment.deadline = chosen.dt
        assignment.deadline_raw = chosen.raw
        assignment.deadline_tz = chosen.tz_label or chosen.zone
        assignment.evidence["deadline"] = chosen.raw
        assignment.evidence["deadline_source"] = (
            f"the {section.role} section" if section is not None else "the whole post"
        )
        if section is None:
            assignment.warnings.append(
                "! Deadline was read from the whole post, not from a role section "
                "assigned to me."
            )
            _lower(assignment, Confidence.LOW)
        elif not labelled:
            assignment.warnings.append(
                "No line labelled 'Deadline' in my section; the date was taken from "
                "the section text."
            )
            _lower(assignment, Confidence.MEDIUM)
        if not chosen.tz_label:
            assignment.warnings.append(
                f"Deadline '{chosen.raw}' names no timezone; "
                f"{config.default_timezone} was assumed."
            )
            _lower(assignment, Confidence.MEDIUM)
        if not chosen.had_time:
            assignment.warnings.append(
                f"Deadline '{chosen.raw}' gives no time of day; "
                f"{config.assume_time} was assumed."
            )
            _lower(assignment, Confidence.MEDIUM)
        others = {c.dt.replace(second=0, microsecond=0) for c in candidates}
        if len(others) > 1:
            assignment.warnings.append(
                "Brief lists deadlines that disagree: "
                + "; ".join(sorted({c.raw for c in candidates}))
            )

    if not chosen and section is not None:
        snippet = " ".join((labelled or scope_text).split())[:120]
        assignment.warnings.append(
            f"! No date could be read from my {section.role} section"
            + (f': "{snippet}"' if snippet else ".")
        )

    assignment.word_count = parse_word_count(scope_text)
    if assignment.word_count:
        assignment.evidence["word_count"] = str(assignment.word_count)

    # --- submissions --------------------------------------------------------
    edited_flags: list[str] = []
    change_talk: list[Message] = []
    for message in thread.messages:
        if opening is not None and message.id and message.id == opening.id:
            continue
        if (
            not message.author.bot
            and not _is_me(message, config)
            and looks_like_deadline_change(message.content)
        ):
            change_talk.append(message)
        if not config.accept_any_author and not _is_me(message, config):
            continue
        links = find_links(message.content, config.submission_link_patterns)
        for attachment in message.attachments:
            links.extend(find_links(attachment.url, config.submission_link_patterns))
        if links:
            assignment.submissions.append(
                Submission(
                    message_id=message.id,
                    posted_at=message.created_at,
                    links=links,
                    jump_url=message.jump_url,
                )
            )
            # A link can be edited into an old message. Discord does not say
            # when the link itself appeared, only when the message was last
            # touched, so flag it when that ambiguity spans the deadline.
            if (
                message.edited_at
                and assignment.deadline
                and message.created_at
                and message.created_at <= assignment.deadline < message.edited_at
            ):
                edited_flags.append(message.id)
    assignment.submissions.sort(key=lambda s: s.posted_at or datetime.max.replace(tzinfo=timezone.utc))

    first = assignment.first_submission
    if first and first.posted_at:
        assignment.replies_after_delivery = sum(
            1
            for m in thread.messages
            if m.created_at
            and m.created_at > first.posted_at
            and not _is_me(m, config)
            and not m.author.bot
        )

    if edited_flags:
        assignment.warnings.append(
            "! My delivery message was edited after the deadline, so the posted time "
            "may not be when the link actually went up."
        )
        _lower(assignment, Confidence.LOW)

    for message in change_talk:
        snippet = " ".join(message.content.split())[:140]
        assignment.warnings.append(
            f'! Someone may have changed the deadline in the thread: "{snippet}" '
            "- the brief above is still what is being tracked."
        )
        _lower(assignment, Confidence.LOW)

    if len(thread.messages) >= config.max_messages_per_thread:
        assignment.warnings.append(
            f"! Thread hit the {config.max_messages_per_thread}-message fetch cap; "
            "later messages were not read."
        )
        _lower(assignment, Confidence.LOW)

    # Having delivered into a thread outranks a mention we read as someone
    # else's: a link of mine in it makes it mine.
    if mine is False and assignment.submissions and not config.accept_any_author:
        mine = True
        assignment.warnings.append(
            "Brief names someone else for this role, but I posted a link here."
        )

    assignment.status = _status_for(assignment, mine, config, now)
    _add_warnings(assignment, config)
    return assignment


def _status_for(
    assignment: Assignment, mine: Optional[bool], config: Config, now: datetime
) -> Status:
    tags_lower = {t.strip().lower() for t in assignment.tags}
    if tags_lower & {t.strip().lower() for t in config.ignore_tags}:
        return Status.IGNORED
    if mine is False:
        return Status.NOT_MINE

    first = assignment.first_submission
    if first:
        if assignment.deadline and first.posted_at and first.posted_at > assignment.deadline:
            return Status.SUBMITTED_LATE
        return Status.SUBMITTED

    if not assignment.deadline:
        return Status.NO_DEADLINE

    remaining = assignment.deadline - now
    if remaining.total_seconds() < 0:
        return Status.OVERDUE
    if remaining <= timedelta(hours=24):
        return Status.DUE_TODAY
    if remaining <= timedelta(hours=config.due_soon_hours):
        return Status.DUE_SOON
    return Status.PENDING


def _add_warnings(assignment: Assignment, config: Config) -> None:
    tags_lower = {t.strip().lower() for t in assignment.tags}
    done_tags = {t.strip().lower() for t in config.done_tags}
    if tags_lower & done_tags and not assignment.submissions:
        assignment.warnings.append(
            "Thread is tagged as delivered but no submission link from me is in it."
        )
    if assignment.submissions and assignment.status.is_submitted:
        if assignment.replies_after_delivery:
            assignment.warnings.append(
                f"{assignment.replies_after_delivery} reply(ies) after my delivery "
                "- check for revision requests."
            )
    if assignment.role and not assignment.assignee_text:
        assignment.warnings.append(
            f"{assignment.role} section names no assignee; assuming it is mine."
        )
    if not assignment.role and not assignment.submissions:
        roles = "/".join(config.my_roles)
        assignment.warnings.append(f"No {roles} section found in the opening post.")


def _fingerprint(assignment: Assignment) -> str:
    """What makes two forwards the same script.

    The title, not the video number: numbers restart per channel, so VIDEO-001
    collides across shows while a title does not. The project joins it, since
    two shows may legitimately use the same title.
    """

    title = (assignment.title or assignment.thread_name or "").lower()
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    project = re.sub(r"[^a-z0-9]+", "", (assignment.project or "").lower())
    return f"{project}|{title}" if title else ""


def _mark_duplicates(items: list) -> None:
    """Keep one copy of each script live and flag the rest.

    Forwarding the same brief twice is easy from a phone, and two copies of one
    script means two countdowns, doubled reminders, and a chart that counts the
    work twice.
    """

    groups: dict = {}
    for assignment in items:
        if assignment.status in (Status.NOT_MINE, Status.IGNORED):
            continue
        key = _fingerprint(assignment)
        if key:
            groups.setdefault(key, []).append(assignment)

    for copies in groups.values():
        if len(copies) < 2:
            continue

        # The copy carrying a delivery wins - that is the thread the work is
        # actually in. Otherwise the most recently forwarded, since a repeat
        # forward is usually a revised brief.
        def rank(a):
            return (
                1 if a.submissions else 0,
                a.assigned_at or datetime.min.replace(tzinfo=timezone.utc),
            )

        ordered = sorted(copies, key=rank, reverse=True)
        kept = ordered[0]
        deadlines = {a.deadline for a in copies if a.deadline}

        kept.warnings.append(
            "Forwarded %d times; the other %s listed as a duplicate."
            % (len(copies), "copy is" if len(copies) == 2 else "copies are")
        )
        for extra in ordered[1:]:
            extra.status = Status.DUPLICATE
            extra.duplicate_of = kept.thread_id
            if len(deadlines) > 1:
                extra.warnings.append(
                    "! Forwarded more than once with different deadlines - check "
                    "which brief is current."
                )
            else:
                extra.warnings.append(
                    'Same script as "%s".' % (kept.title or kept.thread_name)
                )


def build_assignments(
    threads: Iterable[Thread],
    config: Config,
    now: Optional[datetime] = None,
    include_all: bool = False,
    overrides: Optional[dict] = None,
) -> list[Assignment]:
    now = now or datetime.now(timezone.utc)
    table = overrides if overrides is not None else overrides_mod.load(config.overrides_file)

    items = []
    for thread in threads:
        assignment = build_assignment(thread, config, now)
        entry = table.get(str(thread.id))
        if entry:
            overrides_mod.apply(assignment, entry)
            # A corrected deadline or delivery has to re-decide the verdict,
            # unless the override set the verdict itself.
            if (
                ("deadline" in entry or "delivered_at" in entry)
                and "status" not in entry
                and not entry.get("ignore")
            ):
                assignment.status = _status_for(assignment, True, config, now)
        items.append(assignment)

    _mark_duplicates(items)

    if not include_all:
        items = [a for a in items if a.status not in (Status.NOT_MINE, Status.IGNORED)]
    return sort_assignments(items)
