# scriptcheck

Reads your Discord assignment threads, works out which scripts you owe, and tells
you what is **delivered**, **pending**, **due**, or **missed**.

Built for a content-management server laid out like this:

```
Content Allocation
└── #secondary-assignments-workflow
    ├── 09-25-26 | VIDEO-001 | What If Sans Remembered Every RESET?   [Being Written] [Active]
    ├── 10-03-26 | VIDEO-008 | What If Deadpool Joined The Avengers?
    └── ...
```

Each thread's opening post carries a per-role brief:

```
📝 SCRIPT @Josh

• Deadline:
  • 🇺🇸 9/20/2026 @ 11:59 PM ET
    ◦ 🇮🇳 9/21/2026 @ 9:29 AM IST
• Word Count: 5000 Words
```

A **submission** is you posting a Google Drive / Docs link in that thread.
Everything else — chat, "on it", a status tag — is not.

## Example output

```
========================================================================
SCRIPT SUBMISSION CHECK  -  Sun Sep 20, 2026 3:30 PM EDT
========================================================================
OVERDUE: 2  DUE TODAY: 1  PENDING: 1  NO DEADLINE FOUND: 1  DELIVERED: 2

--- OVERDUE (2) ------------------------

🔴 09-23-26 | VIDEO-006 | What If Beyonder Fought The Living Tribunal?
   #secondary-assignments-workflow | 5,000 words | SCRIPT
   Deadline: Fri Sep 18, 2026 11:59 PM EDT  (1d 15h overdue)
   Delivered: NO DRIVE LINK FROM ME IN THIS THREAD
   https://discord.com/channels/900/1003

🔴 09-25-26 | VIDEO-003 | How I'd Survive A Zombie Outbreak
   Deadline: Sat Sep 19, 2026 11:59 PM EDT  (15h 31m overdue)
   ! Thread is tagged as delivered but no submission link from me is in it.
```

Try it right now against the bundled sample data:

```bash
python -m scriptcheck report -i tests/fixtures/sample_threads.json --now 2026-09-20T19:30:00Z
```

## How a status is decided

| Status | Meaning |
| --- | --- |
| `OVERDUE` | Deadline passed, no Drive link from you in the thread. **The one that costs money.** |
| `DUE_TODAY` | Due within 24 hours, nothing delivered. |
| `DUE_SOON` | Due within `due_soon_hours` (default 48). |
| `PENDING` | Assigned to you, deadline further out. |
| `NO_DEADLINE` | Your role section exists but no deadline could be read — **go look manually**. |
| `SUBMITTED` | Drive link posted before the deadline. |
| `SUBMITTED_LATE` | Drive link posted, but after the deadline. |
| `NOT_MINE` | The role section names someone else (hidden unless `--all`). |
| `IGNORED` | Thread carries one of `ignore_tags`. |

Extra flags it raises:

* the thread is tagged *Delivered* but holds no link of yours;
* someone replied after your delivery (possible revision request);
* the brief lists two deadlines that **disagree** (the US and IST lines normally
  describe the same instant — when they don't, you are told and the earlier one wins);
* your role section names nobody.

Deadlines are never guessed. The date in the thread title (`09-25-26`) is the
publish slate, not your deadline, and is deliberately ignored — a thread with no
readable deadline is reported as `NO_DEADLINE` rather than quietly assumed safe.

## Setup

```bash
git clone https://github.com/joshjrath/Scriptwritingchecker.git
cd Scriptwritingchecker
pip install -r requirements.txt      # only needed for the live Discord pull
python -m scriptcheck init           # writes scriptcheck.config.json
```

(`scriptcheck.config.example.json` is the same thing, checked in for reference;
your own `scriptcheck.config.json` is git-ignored. With no config at all the tool
still runs on sensible defaults — it just can't match you by user ID.)

Then put your own Discord user ID in the config (Discord → Settings → Advanced →
Developer Mode, then right-click yourself → Copy User ID). Matching by ID is
exact; matching by display name is the fallback.

### Getting the data in

**Option A — a bot (best, needs a server admin).** Create an application at
<https://discord.com/developers/applications>, add a bot, and under *Bot →
Privileged Gateway Intents* enable **Message Content Intent**. Invite it with
`View Channels` + `Read Message History` on the assignment category. Then:

```bash
export DISCORD_BOT_TOKEN="..."
python -m scriptcheck check          # fetch + report in one go
```

If you are not an admin of *Specular Industries*, someone who is has to invite
the bot — Discord has no supported way for an account to read a server on your
behalf, and automating your own user token is against Discord's terms, so this
tool does not do it.

**Option B — an export (no bot needed).** Export the channel with
[DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) in JSON
format (include threads), then point the reporter at the file or the folder:

```bash
python -m scriptcheck report -i ./exports/
```

**Option C — hand-built JSON.** Any file in the native shape works; see
`tests/make_fixture.py` for a complete, runnable example:

```json
{"version": 1, "threads": [
  {"id": "1001", "name": "09-25-26 | VIDEO-001 | Title",
   "parent_name": "secondary-assignments-workflow", "tags": ["Being Written"],
   "jump_url": "https://discord.com/channels/…",
   "messages": [
     {"id": "2001", "author": {"id": "…", "display_name": "Ash"},
      "content": "📝 SCRIPT @Josh\n• Deadline:\n  • 9/20/2026 @ 11:59 PM ET\n• Word Count: 5000 Words",
      "created_at": "2026-09-19T23:55:00+00:00"}
   ]}
]}
```

## Commands

```bash
python -m scriptcheck fetch                  # pull threads from Discord -> data/threads.json
python -m scriptcheck report                 # the full status report
python -m scriptcheck report --action-only   # only what needs you
python -m scriptcheck report --status OVERDUE,DUE_TODAY
python -m scriptcheck report -f md|json|csv  # other formats
python -m scriptcheck report --all           # include other people's roles
python -m scriptcheck report --now 2026-09-25T09:00:00Z   # ask "where will I stand on Friday?"
python -m scriptcheck check                  # fetch + report
python -m scriptcheck dashboard              # build the web dashboard -> site/index.html
python -m scriptcheck notify --only-if-action             # post the digest to a webhook
```

`report --fail-on-missed` exits `2` when anything is overdue or was delivered
late, so it can gate a cron job or CI step.

## Reminders

Make a Discord webhook in any channel you control — a private server or a DM-like
channel works — and put its URL in `webhook_url` or `$SCRIPTCHECK_WEBHOOK_URL`.

```bash
python -m scriptcheck check && python -m scriptcheck notify --only-if-action
```

`--only-if-action` stays silent unless something is due, overdue, or unreadable,
so a twice-daily schedule is not noise. Run it from cron:

```cron
0 9,19 * * * cd ~/Scriptwritingchecker && python -m scriptcheck check >/dev/null && python -m scriptcheck notify --only-if-action
```

…or from the bundled GitHub Action (`.github/workflows/publish.yml`), which
runs at 9am and 7pm ET. It needs the repo secrets `DISCORD_BOT_TOKEN`,
`SCRIPTCHECK_WEBHOOK_URL` and `SCRIPTCHECK_MY_USER_ID`.

## The board (hosted outside Discord)

`dashboard` renders the whole report as one self-contained HTML file — data
embedded, no server, no build step, nothing to install on the viewing end:

```bash
python -m scriptcheck dashboard -i data/threads.json -o site/index.html
```

The page leads with the single next deadline — a ticking timecode when it is
inside 24 hours — then a **deadline runway** plotting every brief on a time axis
against a NOW line, count tiles that double as filters, a **Needs you now** list
carrying the warnings, and a table of everything with search and sort. It is
frosted glass over a slow gradient, light and dark. Deadlines are formatted in your `display_timezone`
whatever machine opens it, and **statuses are recomputed in the browser** — so a
page built this morning still shows a correct countdown tonight, and a `PENDING`
script that has since passed its deadline shows up as `OVERDUE` without a rebuild.

Where to put it:

| | |
| --- | --- |
| **GitHub Pages** | `.github/workflows/publish.yml` fetches, builds and deploys on a schedule. Zero hosting cost, always current. Pages on a **private** repo needs a paid GitHub plan; on a public repo the page is world-readable. |
| **Any static host** | Netlify drop, S3, Cloudflare Pages, a folder on your own server — it's one file. |
| **Locally** | `python -m scriptcheck dashboard && open site/index.html`. |

**Before you host it publicly, read this.** The page contains client video
titles, deadlines, and your Google Drive links. `--redact-links` keeps the
delivery times and statuses but strips the Drive URLs and the Discord thread
links:

```bash
python -m scriptcheck dashboard -i data/threads.json -o site/index.html --redact-links
```

The bundled workflow passes `--redact-links` by default. Drop it only if the
site is genuinely private.

`--fragment` emits the same page without the `<html>`/`<body>` wrapper, for
embedding in a host that supplies its own document shell.

## Configuration

`scriptcheck.config.json`, all keys optional:

| Key | Default | What it does |
| --- | --- | --- |
| `my_user_ids` | `[]` | Discord user IDs that count as you (exact match). |
| `my_names` | `["Josh"]` | Usernames / nicknames, used when no ID is available. |
| `my_roles` | `["SCRIPT"]` | Role sections you are responsible for. |
| `known_roles` | SCRIPT, VOICE OVER, THUMBNAIL, EDIT, … | Headers used to split a brief into sections. |
| `guild_ids` / `channel_ids` | `[]` | Restrict the fetch. |
| `channel_name_patterns` | `[]` | Regexes matched against channel names when no IDs are given. |
| `include_archived` | `true` | Also walk archived threads. |
| `max_messages_per_thread` | `300` | Fetch depth per thread. |
| `default_timezone` | `America/New_York` | Assumed when a deadline gives no timezone. |
| `preferred_timezones` | `["America/New_York"]` | Which spelling of a multi-timezone deadline to quote. |
| `display_timezone` | `America/New_York` | Timezone the report prints in. |
| `assume_time` | `"23:59"` | Clock time assumed for a date-only deadline. |
| `date_order` | `"MDY"` | Set to `"DMY"` if your server writes day-first dates. |
| `due_soon_hours` | `48` | The `DUE_SOON` window. |
| `submission_link_patterns` | Drive + Docs | Regexes that make a link count as a delivery. |
| `accept_any_author` | `false` | Count a link from anyone, not just you. |
| `done_tags` / `ignore_tags` | see config | Forum tags treated as delivered / skipped. |
| `webhook_url` | `""` | Where `notify` posts. |
| `data_file` | `data/threads.json` | Default fetch/report path. |

## Tests

```bash
python -m unittest discover -s tests -t .
```

48 tests cover title and deadline parsing (including the two-timezone briefs,
Discord `<t:…>` timestamps, date-only deadlines and month-name dates), role-section
assignment, link detection, every status transition, the report formats, and the
dashboard's data embedding (including that a thread title cannot break out of the
embedded JSON).
