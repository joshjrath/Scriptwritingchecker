<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" alt="scriptcheck" width="340">
  </picture>
</p>

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

## Start here

```bash
git clone https://github.com/joshjrath/Scriptwritingchecker.git
cd Scriptwritingchecker
bash start.command
```

That is the whole thing. It installs what it needs, asks four questions
(Application ID, bot token, your user ID, which channel), writes the config,
checks the bot can see everything, and opens the board. Run it again any time
to start the board — it only asks once.

On a Mac you can also just double-click `start.command` in Finder.

Everything below is reference for when you want to change something.

## Setup (by hand)

```bash
git clone https://github.com/joshjrath/Scriptwritingchecker.git
cd Scriptwritingchecker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # only needed for the live Discord pull
cp .env.example .env                 # then fill in the four values
python -m scriptcheck init           # writes scriptcheck.config.json
```

`.env` is read automatically by every command, so there is no `export` or
`source` step to forget. Real environment variables always win, so a hosted
deploy ignores a stray `.env` in the image.

(`scriptcheck.config.example.json` is the same thing, checked in for reference;
your own `scriptcheck.config.json` is git-ignored. With no config at all the tool
still runs on sensible defaults — it just can't match you by user ID.)

Then put your own Discord user ID in the config (Discord → Settings → Advanced →
Developer Mode, then right-click yourself → Copy User ID). Matching by ID is
exact; matching by display name is the fallback.

### Setting up the bot (once, then never again)

**1. Create the application.** <https://discord.com/developers/applications> ->
*New Application*. Under **Bot**, click *Reset Token* and copy it — that string
is the bot's password, so treat it like one and never commit it.

**1b. Leave "Public Bot" ON.** It is on by default, and the instinct to turn it
off is wrong here: with it off, *only the application owner* can install the
app, and installing into a server requires Manage Server there. Since an admin
of someone else's server is doing the install, the app has to stay public. It
does not mean anyone can read your data - the bot still only sees servers it is
invited to.

**2. Turn on the intent that everyone forgets.** Same page: *Privileged Gateway
Intents* -> enable **MESSAGE CONTENT INTENT**. Without it every message arrives
with empty text, so every brief looks blank and nothing parses. `doctor` checks
this explicitly because it is the single most common way this setup silently
does nothing.

**3. Get the invite URL.** Copy the *Application ID* from the General
Information page, then:

```bash
python -m scriptcheck invite --client-id <APPLICATION_ID>
```

That prints a URL granting **View Channels + Read Message History only**
(permissions `66560`) — the bot cannot post, edit, delete, or react. Send it to
an admin of the server. Below is a message you can paste as-is:

> Hey — I built a small tool that watches my assignment threads and tells me
> what I still owe, so nothing slips. It needs a read-only bot in the server to
> see the threads I'm assigned to.
>
> It's **read-only**: View Channels and Read Message History, nothing else. It
> can't post, edit, delete, or react. It reads the assignment channels only, and
> it runs twice a day on a schedule — it isn't online otherwise.
>
> Invite link: `<paste the URL here>`
>
> If you'd rather scope it tighter, you can restrict the bot's role to just the
> Content Allocation category and it'll work the same.

**4. Prove it works.**

```bash
export DISCORD_BOT_TOKEN="..."
python -m scriptcheck doctor
```

`doctor` checks login, server membership, channel visibility, read-history
permission, thread reachability, whether sampled messages actually carry text
(the intent check), and whether your configured user ID really appears in the
threads. Every failure comes with the specific fix. When it says *"Everything
checks out"*, the unattended pipeline will work.

**5. Point it at your server.** `python -m scriptcheck init` writes a config;
set `my_user_ids` to your own ID and check `channel_name_patterns` matches the
assignment channel's name. `.env.example` lists the four environment variables
and where each one comes from.

**6. Let it run itself.** Add three repository secrets — `DISCORD_BOT_TOKEN`,
`SCRIPTCHECK_MY_USER_ID`, `SCRIPTCHECK_WEBHOOK_URL` — and enable Pages
(*Settings -> Pages -> Source: GitHub Actions*). After that the workflow
preflights, fetches, audits, publishes the board, and pings you twice a day.

### Nothing here fails silently

A scheduled job you have to remember to check is not automation. So:

* **The run preflights before it fetches**, so a bot that lost access can't
  quietly publish an empty board.
* **A failed run posts to your webhook**, saying the board is stale and not to
  be trusted. Silence never means "broken".
* **Monday mornings get a full digest** even when nothing is owed — proof of
  life, so a quiet week is distinguishable from a dead workflow.
* **The board shows its own age** and marks itself stale past 24 hours.
* One thing to know: **GitHub disables scheduled workflows after 60 days of
  repository inactivity** and emails the owner. The Monday digest is your
  tripwire — if it stops arriving, re-enable the workflow in the Actions tab.

### Without a bot

If the invite ever falls through, everything except `fetch` still works on an
export: run [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter)
over the channel in JSON (include threads) and point the reporter at it —
`python -m scriptcheck report -i ./exports/`. Any file in the native shape works
too; `tests/make_fixture.py` is a runnable example of it.

## Commands

```bash
python -m scriptcheck invite --client-id ID  # print the read-only invite URL
python -m scriptcheck invite --client-id ID --dropbox   # for a server you own
python -m scriptcheck doctor                 # prove the bot can see everything
python -m scriptcheck serve                  # LIVE: gateway + web server
python -m scriptcheck deploy                 # everything needed to host it
python -m scriptcheck fetch                  # pull threads from Discord -> data/threads.json
python -m scriptcheck report                 # the full status report
python -m scriptcheck report --action-only   # only what needs you
python -m scriptcheck report --status OVERDUE,DUE_TODAY
python -m scriptcheck report -f md|json|csv  # other formats
python -m scriptcheck report --all           # include other people's roles
python -m scriptcheck report --now 2026-09-25T09:00:00Z   # ask "where will I stand on Friday?"
python -m scriptcheck check                  # fetch + report
python -m scriptcheck audit                  # how much was read vs assumed
python -m scriptcheck explain "Sans"         # full parse trace for one thread
python -m scriptcheck dashboard              # build the web dashboard -> site/index.html
python -m scriptcheck notify --only-if-action             # post the digest to a webhook
```

`report --fail-on-missed` exits `2` when anything is overdue or was delivered
late, so it can gate a cron job or CI step.

## Drop-box mode (no access to their server)

If the server you write for will not host a bot — a normal answer, and not one
worth arguing with — nothing here needs their permission. The bot lives in a
server **you** own and never touches theirs.

When an assignment lands, **forward the brief** into your own channel. One tap
on mobile. The bot recognises it, opens a thread on it, and from that moment the
deadline, the countdown, the 24h and 2h reminders and the board all work exactly
as they do in the connected version. Post your Drive link in that thread and it
flips to Delivered.

Two taps per assignment instead of none. Everything else is unchanged.

```bash
python -m scriptcheck invite --client-id <APPLICATION_ID> --dropbox
```

That grants View Channels, Read Message History, **Create Public Threads** and
Send Messages in Threads — the extra two only so it can open the thread your
delivery goes in. You open the link yourself; nobody else is involved.

```json
{
  "dropbox_channel_patterns": ["my-assignments"],
  "auto_thread": true,
  "my_roles": ["SCRIPT"]
}
```

Any channel whose name matches is read in drop-box mode: each message that
parses as a brief becomes an assignment, and anything you post in its thread —
or as a reply to it — is a follow-up. Chat that is not a brief is ignored, so a
stray "thanks!" never becomes a tracked assignment with no deadline.

**Forwarded messages arrive with empty `content`** — Discord puts the original
text in a snapshot — so the text, embeds and attachments of a forward are all
read explicitly. Reading only `content` would make every forwarded brief look
blank, which is the one thing that would quietly break this whole path.

Pasting a brief in as text works identically, if forwarding ever mangles one.

### Forwarding the same brief twice

Easy to do from a phone, and two copies of one script means two countdowns,
doubled reminders and a chart that counts the work twice. So repeat forwards are
detected and collected into their own **Forwarded twice** section, out of the
counts, the chart, the table and the alerts.

Two forwards are the same script when the **title and project** match, ignoring
case and punctuation - not the video number, which restarts per channel. Of the
copies, the one carrying a delivery wins, since that is the thread the work is
actually in; otherwise the most recent, since a repeat forward is usually a
revised brief. If the copies disagree about the deadline that is said out loud
rather than quietly resolved, because a moved deadline and a stray double-tap
look identical to a parser.

### Marking things delivered

The delivery itself happens in *their* server, where this bot cannot see — so in
drop-box mode there is nothing to detect. The board carries a **mark delivered**
button on every open assignment instead: one tap, and it flips with the margin
against the deadline. **undo** puts it back.

That writes to `overrides.json`, the same file that holds every other hand
correction, so it shows up as `Corrected by hand`, survives restarts, and is
never silently reverted by a later parse.

**On a hosted container, point it at a volume.** Railway, Fly and Render throw
the filesystem away on every deploy, so an ordinary path is writable but not
durable. Mount a volume at `/data` and set `"overrides_file": "/data/overrides.json"`
in `SCRIPTCHECK_CONFIG`. The daemon warns at startup if the path looks
ephemeral, and the button reports the problem rather than failing quietly.

If you would rather not tap anything: forward your own delivery message into the
thread the same way you forwarded the brief, and it is detected normally.

## Real time

`serve` runs the board as a live process: one Discord gateway connection and a
small web server in the same loop. Discord **pushes** events, so nothing polls —
a message lands, the affected thread is re-read, the board is recomputed, and
every open browser updates over SSE, usually inside a second.

```bash
export DISCORD_BOT_TOKEN="..."
export SCRIPTCHECK_ACCESS_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
python -m scriptcheck serve
# board on http://0.0.0.0:8080/?k=<your token>
```

| Route | |
| --- | --- |
| `/` | the board, in live mode |
| `/events` | SSE stream; the page reconnects with backoff on its own |
| `/report.json` | current state as JSON |
| `/healthz` | `200` when the gateway is connected and a sync has happened, `503` otherwise — point your host's health check here |
| `POST /mark` | mark an assignment delivered by hand, or undo it |
| `/audit` | the parse audit as plain text |
| `/explain?q=Sans` | full parse trace for one thread; `/explain` alone lists them |

`/audit` and `/explain` matter because calibration otherwise needs a terminal.
Behind the access token like everything else, they make it possible to check
what the parser did from a phone. The scheduled workflow has the same escape
hatch: run it from the Actions tab with an `explain` input and the trace appears
in the job log.

### What updates instantly

| Event | Effect |
| --- | --- |
| You post a Drive link | row flips to **Delivered**, with the margin against the deadline |
| A new assignment thread appears | it shows up, and you get a ping |
| The opening post is edited | the deadline is re-read — this is how a changed brief stops being stale |
| A message is edited or deleted | that thread is re-evaluated |
| Forum tags or the title change | re-read |
| A deadline passes | **Overdue**, pushed to the page and to your webhook |

Bursts are debounced (1.5s) so a flurry of messages causes one re-read, and a
full resync runs every `resync_minutes` regardless — gateway events can be
missed during a reconnect, and a board that is quietly wrong is worse than one
that is briefly late.

### Alerts before the deadline, not after

This is the part a twice-daily cron cannot do. The daemon pings you at each
`reminder_lead_hours` window (default 24h and 2h out), when something goes
overdue, when a new script lands, when one is delivered, and when a deadline
appears to move.

Each alert fires **once** per assignment per deadline value. A restart is silent
— anything already inside a window is treated as spent — and arriving inside
several windows at once sends one message, not a burst. If a deadline is moved,
the reminders re-arm for the new one.

```json
{
  "reminder_lead_hours": [24, 2],
  "alert_kinds": ["new_assignment", "due_in", "overdue", "delivered", "deadline_changed", "needs_review"],
  "resync_minutes": 15
}
```

Drop any kind from `alert_kinds` to stop hearing about it.

### Configuring a host with no filesystem

On Railway, Render or Fly there is no config file to edit, so the whole config
can travel as one variable — `SCRIPTCHECK_CONFIG`, holding the JSON inline:

```
SCRIPTCHECK_CONFIG={"my_roles":["SCRIPT"],"channel_name_patterns":["assignments","workflow"],"display_timezone":"America/New_York"}
```

`SCRIPTCHECK_MY_USER_ID`, `SCRIPTCHECK_WEBHOOK_URL` and `SCRIPTCHECK_ACCESS_TOKEN`
layer on top of it, so secrets stay in their own variables. A malformed value is
rejected at startup with the reason, rather than silently falling back to
defaults. `SCRIPTCHECK_CONFIG_FILE` points at a path instead, if you mount one.

Leaving `channel_name_patterns` empty means *every* channel gets read; the
daemon warns about that at startup.

### Where to run it

A gateway connection has to stay open, so this needs somewhere always-on. It is
a 256MB process that idles at almost nothing.

| | |
| --- | --- |
| **Fly.io** | `fly.toml` is included and sets `auto_stop_machines = false` — the machine must not sleep or the connection drops. A few dollars a month at the smallest size. |
| **A Raspberry Pi or any spare box** | `deploy/systemd-scriptcheck.service` is a ready unit file with `Restart=always`. Free, and the board stays on your own network. |
| **Railway** | `railway.json` and the `Dockerfile` are included and it deploys from GitHub in a browser — no terminal, no CLI. Configure it with the variables above. |
| **Any VPS / Render paid tier** | `Dockerfile` included, health check wired to `/healthz`. |
| **Render free tier, or anything that sleeps on idle** | won't work — a sleeping process is a disconnected bot. |

### Putting it online

```bash
python -m scriptcheck deploy
```

Reads your working local setup and prints the numbered Railway steps plus one
block to paste into its bulk variable editor — including `SCRIPTCHECK_CONFIG`
built from your config file with `overrides_file` already pointed at the mounted
volume. Then it prints both of your links with the real tokens in them.

The block contains your bot token, so it goes into the host and nowhere else.

### Your own logo and name

Two variables, no code and no redeploy of your own:

```
SCRIPTCHECK_LOGO_URL=https://.../logo.png
SCRIPTCHECK_BOARD_TITLE=Specular Scripts
```

The easiest way to get a URL for an image you have: post it in a Discord channel
you own, then copy the image's link. The title replaces the header text and the
browser tab. If the logo URL ever breaks or expires, the page quietly falls back
to the drawn mark rather than showing a broken image.

### Sharing the board with a team

Two tokens, two levels:

| | |
| --- | --- |
| `SCRIPTCHECK_ACCESS_TOKEN` | yours. Full board, the *mark delivered* buttons, `/audit` and `/explain`. |
| `SCRIPTCHECK_VIEW_TOKEN` | the link you hand out. Same board, read-only: no buttons, no writes, and no `/audit` or `/explain` (those quote the briefs back in full). |

```
https://your-host/?k=<view token>
```

A viewer's page says *Read-only view* across the top, and their event stream is
served its own payload, so a later push never hands them edit rights. Everything
else — countdowns, statuses, live updates — is identical.

Both tokens are generated for you by `scriptcheck setup`. To rotate the shared
one, change `SCRIPTCHECK_VIEW_TOKEN` and restart; old links stop working
immediately and yours is unaffected.

**Lock it down.** Unlike the GitHub Pages build, this board is a live URL with
client titles, deadlines and Drive links on it. Set `SCRIPTCHECK_ACCESS_TOKEN`
and reach it at `/?k=<token>` — the token is then remembered in a cookie, and
every other request without it returns `404` rather than `403`, so a stranger
learns nothing. The daemon logs a warning at startup if no token is set.

### Or keep the scheduled version

`.github/workflows/publish.yml` still works and costs nothing to run. The two
modes share all their logic, so you can start on the cron and move to `serve`
later without changing anything else.

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

## Accuracy

Every parsing rule in this tool was inferred from screenshots of the workflow,
not from your real threads. Treat the first live run as **unverified** until the
audit says otherwise. The design principle throughout is that the tracker is
allowed to be unsure, and is never allowed to be confidently wrong: anything it
had to assume is reported as an assumption.

### Confidence

Every assignment carries a confidence level, shown in the report, the CSV, and
as a `check` badge on the board:

| | |
| --- | --- |
| `HIGH` | Assignee matched by Discord **user ID**, deadline read from a `Deadline:` line inside your own role section, with an explicit timezone. |
| `MEDIUM` | Something was resolved more loosely — matched by display name, no timezone given, no time of day given, or no line actually labelled `Deadline`. |
| `LOW` | Something material had to be guessed, or a signal says the row may be stale: the deadline came from outside your role section, the post has two sections for your role, a delivery message was edited after the deadline, the thread hit the fetch cap, or someone appears to have changed the deadline in conversation. |

### Calibrating against your real threads

```bash
python -m scriptcheck fetch                  # pull the real data once
python -m scriptcheck audit                  # how much was read vs assumed
python -m scriptcheck explain "Sans"         # what exactly happened in one thread
```

`audit` prints coverage (what fraction of briefs yielded a role section, an
assignee, a deadline), lists every assignment needing a human look, and — the
important part — **names role headers it saw but does not know about**. If your
briefs say `WRITER` and `known_roles` says `SCRIPT`, that assignment would
otherwise vanish silently; the audit surfaces it instead.

`explain` prints the full trace for one thread: which role sections were found,
who each names, which line the deadline was read from, what was assumed, and the
opening post exactly as fetched. When a row looks wrong, this tells you why in
one screen.

Fix what it finds by editing the config (`known_roles`, `my_names`,
`submission_link_patterns`, `date_order`) — or, when a single thread is just
odd, by hand:

### overrides.json

Corrections keyed by thread ID. They beat the parser, are shown in the report as
`Corrected by hand`, and never silently revert:

```json
{
  "1412…": { "deadline": "2026-09-25T23:59:00-04:00", "note": "Ash extended it in thread" },
  "1398…": { "delivered_at": "2026-09-19T20:00:00-04:00", "links": ["https://drive.google.com/…"] },
  "1377…": { "ignore": true, "note": "cancelled" },
  "1355…": { "status": "SUBMITTED" }
}
```

A corrected deadline or delivery re-decides the status; an explicit `status`
wins outright. Unknown keys are rejected loudly rather than ignored.

### What it deliberately will not do

* **Guess a deadline.** No readable date in your section → `NO_DEADLINE`, never
  a fallback to the title's publish slate.
* **Follow a deadline change in conversation.** "Take an extra day" is detected
  and flagged, but the brief stays the source of truth — acting on a parsed
  guess about a schedule change is worse than being told to go read the thread.
  Confirm it, then put it in `overrides.json`.
* **Credit someone else's link as yours**, or count a message that merely talks
  about the script.

### Known limits

* Delivery time comes from when the message was *posted*. Discord does not say
  when a link was edited into a message, so a message edited after its deadline
  is flagged as uncertain rather than judged.
* Only threads in the configured channels are read, only up to
  `max_messages_per_thread` messages each — the cap being hit is reported.
* A script delivered by DM, in another channel, or as a non-Drive attachment is
  invisible. Widen `submission_link_patterns` if your team uses something else.
* Revisions are not modelled: the **first** qualifying link is the delivery.
  Replies after it are counted and flagged as possible revision requests.

## The board (hosted outside Discord)

`dashboard` renders the whole report as one self-contained HTML file — data
embedded, no server, no build step, nothing to install on the viewing end:

```bash
python -m scriptcheck dashboard -i data/threads.json -o site/index.html
```

The page leads with the single next deadline — a ticking timecode when it is
inside 24 hours — then a **scripts due** chart: a column per day
counting what is owed, with everything overdue collected in one column at the
left and anything past the window in "Later". Each script is its own block, so a
column can be counted as well as read, and two scripts on Thursday is visibly a
different Thursday from one. Below that, count tiles that double as filters, a **Needs you now** list carrying the
warnings, and a table of everything with search and sort. Deadlines are formatted in your `display_timezone`
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
| `dropbox_channel_patterns` | `[]` | Channels in your own server where you forward briefs. |
| `auto_thread` | `true` | Open a thread on each forwarded brief. |
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
| `logo_url` | `""` | Your logo, as a URL the browser can reach. |
| `board_title` | `Script Board` | Header text and browser tab title. |
| `webhook_url` | `""` | Where `notify` and live alerts post. |
| `access_token` | `""` | Your own secret for the live board; empty means open. |
| `view_token` | `""` | Read-only secret to share with a team. |
| `serve_host` / `serve_port` | `0.0.0.0` / `8080` | Where `serve` binds. |
| `resync_minutes` | `15` | Safety-net full resync in live mode. |
| `reminder_lead_hours` | `[24, 2]` | How far ahead of a deadline to ping. |
| `alert_kinds` | all six | Which live alerts to send. |
| `data_file` | `data/threads.json` | Default fetch/report path. |
| `overrides_file` | `overrides.json` | Hand corrections that beat the parser. |

## Tests

```bash
python -m unittest discover -s tests -t .
```

218 tests cover title and deadline parsing (including the two-timezone briefs,
Discord `<t:…>` timestamps, date-only deadlines and month-name dates), role-section
assignment, link detection, every status transition, the report formats, and the
dashboard's data embedding (including that a thread title cannot break out of the
embedded JSON), plus the accuracy machinery: confidence levels, deadline-change
detection, edited-message ambiguity, fetch-cap reporting, unknown role discovery
and the overrides file, plus every preflight rule (bad token, missing invite,
unreadable channel, the message-content intent being off) against synthetic facts,
so the diagnosis is verified without a live connection. The live daemon is covered
too: alert timing and once-only firing against a moving clock, and the HTTP surface
(auth gate, health, JSON, and a real SSE push reaching a connected client) driven
through aiohttp's test server, with no Discord involved. Drop-box mode is covered
end to end, including that a forwarded message's text, embeds and attachments are
read out of its snapshot rather than its empty body.
