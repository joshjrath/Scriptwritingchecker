"""Turn raw threads into assignments with a status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .config import Config
from .models import Assignment, Message, Status, Submission, Thread, sort_assignments
from .parsing import (
    RoleSection,
    choose_deadline,
    deadline_text,
    extract_datetimes,
    find_links,
    mentions,
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
    sections = split_role_sections(body, config.known_roles)
    section, mine = _pick_section(sections, config)

    if section is not None:
        assignment.role = section.role
        assignment.assignee_text = ", ".join(
            section.mention_names + [f"<@{i}>" for i in section.mention_ids]
        )
    scope_text = section.text if section is not None else _without_title_line(body, thread.name)

    # --- deadline -----------------------------------------------------------
    focus = deadline_text(scope_text) or (scope_text if section is not None else "")
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
        others = {c.dt.replace(second=0, microsecond=0) for c in candidates}
        if len(others) > 1:
            assignment.warnings.append(
                "Brief lists deadlines that disagree: "
                + "; ".join(sorted({c.raw for c in candidates}))
            )

    assignment.word_count = parse_word_count(scope_text)

    # --- submissions --------------------------------------------------------
    for message in thread.messages:
        if opening is not None and message.id and message.id == opening.id:
            continue
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


def build_assignments(
    threads: Iterable[Thread],
    config: Config,
    now: Optional[datetime] = None,
    include_all: bool = False,
) -> list[Assignment]:
    now = now or datetime.now(timezone.utc)
    items = [build_assignment(t, config, now) for t in threads]
    if not include_all:
        items = [a for a in items if a.status not in (Status.NOT_MINE, Status.IGNORED)]
    return sort_assignments(items)
