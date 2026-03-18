# Personal Agentic Team
## Product Requirements Document

| | |
|---|---|
| **Author** | Sam |
| **Date** | March 2026 |
| **Version** | 1.2 — Added Free-Form Conversation & Routing |
| **Status** | Ready for V1 Implementation |
| **Budget** | $50/month all-in (infra + AI API) |
| **Target Stack** | Claude API · Raspberry Pi · GitHub · Linear · Google Drive · Telegram · Vercel |

---

## 1. Overview

This document describes the architecture, requirements, and phased implementation plan for a personal agentic team — a system of AI agents that autonomously handle personal productivity tasks and software development work on Sam's behalf.

The system is designed around three interaction surfaces: a Telegram bot as the primary day-to-day interface (supporting both slash commands and natural free-form conversation), Claude Cowork for longer review sessions, and a web-based observability dashboard (a V3 dog-food project). A Raspberry Pi running a Python scheduler serves as the orchestration backbone. All human-facing communication flows through Telegram.

### 1.1 Goals

- Reduce the manual overhead of managing side projects by delegating research, ticket creation, coding, and QA to autonomous agents
- Create a personal assistant that handles recurring and ad-hoc life tasks via natural conversation — no commands required
- Build toward a fully autonomous dev team that writes production-grade code, opens PRs, runs QA feedback loops, and only surfaces work to Sam for final review and merge
- All agent communication flows through Telegram: natural language in, reports and approvals out
- Stay within a $50/month all-in budget for infra and AI API costs
- Maintain full observability — every agent decision is logged and searchable

### 1.2 Non-Goals (V1)

- Agents do not autonomously merge code — Sam always controls merges
- No self-hosted LLMs — all inference goes through the Claude API
- No email or calendar integration in V1
- No mobile app — Telegram handles mobile; Cowork desktop for longer sessions

---

## 2. Telegram Bot — Interaction Layer

Telegram is the primary communication layer between Sam and the agent team. A single bot handles all four agents, supporting both explicit slash commands and natural free-form conversation. The bot runs as a long-polling Python process on the Raspberry Pi alongside the scheduler, sharing the same utilities package.

### 2.1 Security Model

The bot is locked to Sam's Telegram user ID. Every incoming message handler checks the sender's ID against a hardcoded allowlist as its first operation. Any message from an unknown user is silently dropped — no error, no response, no log. The bot token is stored as an environment variable on the Pi and never committed to any repository.

### 2.2 Command Reference

| Command | Routes To | Description |
|---|---|---|
| `/plan [description]` | Manager | Break a plain-English project idea into Linear tickets. Presents for Telegram approval before creating in Linear. |
| `/dev [task]` | Developer | Trigger the Developer agent on an ad-hoc task, bypassing the Manager ticket flow |
| `/research [topic]` | Researcher | Kick off a research brief. Summary delivered in Telegram; full doc saved to Drive. |
| `/meal` | PA | Manually trigger the weekly infant meal plan outside the Friday schedule |
| `/status` | Manager | Instant board summary: in-progress tickets, blockers, last Developer run |
| `/logs [n]` | Observability | Plain-English summary of the last n agent runs with running cost total |
| `/approve [id]` | Manager | Approve a pending action (ticket batch, prompt update proposal, etc.) |
| Free-form message | Auto-routed | Natural language auto-routed to the best agent. Agent shown in response prefix. |

### 2.3 Free-Form Conversation & Routing

Any message that is not a slash command is passed through a lightweight router before being handled. The router is a fast Claude Haiku call that reads the message and returns a routing decision: `pa`, `manager`, `researcher`, `developer`, or `clarify`. The full message is then forwarded to the selected agent with the active conversation context attached.

#### Routing Logic

- **Personal intent** — shopping research, parenting questions, recipes, travel, general Q&A → PA
- **Project intent** — feature ideas, prioritization, board questions, status → Manager
- **Technical investigation** — architecture questions, library comparisons, how-to research → Researcher
- **Direct dev task** — free-form dev requests route to Manager first, which creates a ticket and fast-tracks to Developer if small enough. Use `/dev` to bypass.
- **Low confidence** — router returns `clarify` and bot sends inline buttons: `[📋 Create ticket]` `[🔍 Research this]` `[💬 Ask PA]`

#### Agent Attribution

Every auto-routed response is prefixed with a subtle agent tag so Sam always knows who responded:

```
Sam: find infant shoes for a new walker, wide toe box, flexible sole, under $50

🟦 PA · searching...

Here are some strong options for a new walker:
  1. Stride Rite Soft Motion — $42, extra-wide available, very flexible sole
  2. See Kai Run — $48, podiatrist-recommended, great toe box
  3. Robeez Soft Soles — $35, best for early walkers, fully flexible

All available at major retailers. Want me to check stock near you?
```

```
Sam: what should I do about the property detail page

Not sure how to handle this — did you mean:
  [📋 Create a ticket]  [🔍 Research options]  [💬 Ask PA]
```

### 2.4 Conversation Context

Each agent maintains a rolling context window of the last 10 messages (5 exchanges) per Telegram chat session, stored in memory on the Pi in a Python dict keyed by chat ID. Context is per-agent — PA maintains its own thread, Manager its own, and so on — so switching between agents mid-conversation does not bleed context across them.

| Parameter | Value |
|---|---|
| Context window | Last 10 messages (5 exchanges) per agent |
| Scope | Per-agent, per-chat-session — no cross-agent bleed |
| Inactivity reset | 30 minutes — new conversation starts fresh after idle |
| Storage | In-memory Python dict on Pi (not persisted to disk) |
| Scheduled job context | Stateless — scheduled runs never use Telegram context |

```
Sam: find infant shoes for a new walker, wide toe box, flexible sole, under $50
🟦 PA: Here are some strong options... [lists shoes]

Sam: actually make it under $40
🟦 PA: Filtering to under $40 — the Robeez Soft Soles at $35 are your
  best bet from the previous list. Also worth considering:
  Babybotte Ariel — $38, very wide toe box, leather upper.
```

### 2.5 Interaction Examples

```
Sam: /plan add authentication to my BRRRR app

Manager: Got it. Here's the breakdown I'm proposing:
  Epic: Authentication (5 tickets)
  • ENG-44: Set up NextAuth.js with Google provider
  • ENG-45: Add session middleware to API routes
  • ENG-46: Build login/logout UI
  • ENG-47: Protected route wrapper component
  • ENG-48: Write auth integration tests

  Reply /approve plan-44 to create in Linear, or tell me what to change.
```

```
Developer: ✅ Picked up ENG-44 (NextAuth.js setup)

  Branch: feature/ENG-44-nextauth-setup
  Commits: 3  |  Tests: 12 passed, 0 failed
  PR #51: https://github.com/sam/brrrr-app/pull/51

  Linear ticket updated to In Review.
```

```
PA: 🥑 Weekly meal plan ready!

  This week's theme: iron-rich foods for 11-month-olds
  1. Lentil puree with roasted sweet potato
  2. Soft scrambled egg with avocado
  3. Chicken and butternut squash mash
  [+ 4 more recipes]

  Shopping list sorted by Whole Foods and Trader Joe's sections.
  Full doc: https://drive.google.com/...
```

```
Manager: 📊 Daily digest — Tuesday March 11

  ✅ In progress: ENG-44 (auth setup) — PR #51 awaiting your review
  ⏳ Blocked: ENG-39 (map component) — stuck 2 days, needs Mapbox API key
  🟡 Ready: ENG-45, ENG-46 queued for tomorrow

  Budget: $18.40 used of $50.00 this month.
```

### 2.6 Approval Flow via Inline Buttons

For actions requiring Sam's confirmation — creating a ticket batch, applying a system prompt update, running a costly research task — the bot sends an inline keyboard with Approve and Edit/Cancel buttons. This removes the need to type a follow-up command and keeps the flow native to Telegram.

### 2.7 File Delivery

Agents send files directly via Telegram when appropriate: the PA attaches the full meal plan doc, the Researcher attaches the research brief, the Developer can attach screenshots of UI changes. Files are always also saved to Google Drive as the permanent record.

---

## 3. Agent Roster

The system comprises four specialized agents, each with a defined role, tool access, schedule, and conversational scope. All agents share a common logging schema and read their behavior from living system prompt files in the private ops repo. All human-facing output is delivered via Telegram.

| Agent | Role | Schedule | Primary Tools | Conversational Scope |
|---|---|---|---|---|
| Personal Assistant | Meal planning, research, shopping, life Q&A | Weekly (Fridays) + on-demand | Claude API, Google Drive | Anything personal, life, family, shopping, research, general Q&A |
| Dev Manager | Ticket grooming, blocker reports, team coordination | Daily + on-demand | Linear API, GitHub, Google Drive | Project intent, feature ideas, board questions, prioritization |
| Researcher | Technical research, spike investigations | On-demand | Claude API + web search, Drive, GitHub | Technical questions needing investigation rather than immediate action |
| Developer | Ticket implementation, code authoring, PR creation | Daily (morning) + /dev command | Claude Code, GitHub, Linear API | Direct code tasks via /dev only — free-form dev requests route via Manager |

### 3.1 Personal Assistant

The PA is the most conversational agent. It handles both scheduled life tasks and any free-form personal question or research request. It maintains conversation context, supports follow-up questions, and is the default destination for anything that doesn't clearly belong to another agent.

**Scheduled Jobs**
- Every Friday: Generate a high-protein, nutrient-dense meal plan for an 11-month-old infant. Deliver via Telegram with inline recipe summaries and a shopping list sorted by store section (Whole Foods and Trader Joe's). Full doc saved to Google Drive.

**Conversational Scope**
- Shopping research with specifications (e.g. infant shoes, stroller comparisons, product recommendations)
- Parenting and infant development questions
- Recipe requests and food ideas beyond the scheduled meal plan
- Travel research, local recommendations, general knowledge questions
- Follow-up and refinement of any previous PA response within the session

**On-Demand Commands**
- `/meal` — manually trigger the weekly meal plan
- `/research [topic]` — longer-form research summary saved to Drive
- Free-form messages — auto-routed here for personal and life topics

**Living System Prompt:** `agents/pa/system-prompt.md` in the private ops repo

### 3.2 Dev Manager

The Manager owns the Linear board and is the central coordinator of the dev team. It handles both scheduled reporting and conversational project management — you can describe a feature idea naturally and it will translate it into structured tickets.

**Scheduled Jobs**
- Daily at 9am: Scan Linear for blockers (tickets stuck >24h). Send digest to Telegram.
- Weekly: Review PR comments for repeated feedback patterns. Propose system prompt updates via Telegram inline approval.

**Conversational Scope**
- Feature ideas and project descriptions — converted to ticket proposals
- Prioritization requests — "de-prioritize the map stuff" updates Linear directly with confirmation
- Status questions — "what are we working on this week?" returns a board summary
- Blocker questions — "what's blocking the auth ticket?" returns ticket context
- Free-form dev requests — creates a ticket and fast-tracks to Developer if small enough

**Agentic Inbox**

A Google Drive doc at `agents/manager/inbox/ideas.md`. Sam can drop rough ideas here at any time. The Manager checks on its daily run, converts entries to ticket proposals, delivers via Telegram for approval, then clears the entry.

### 3.3 Researcher

Spun up on-demand by the Manager or via `/research`. Handles technical questions that need investigation rather than an immediate answer. Responds conversationally for quick follow-up questions within a session.

**Conversational Scope**
- Architecture and library comparison questions (e.g. "compare Supabase vs PlanetScale for my use case")
- Best-practice questions (e.g. "how should I handle optimistic UI updates in React Query?")
- Follow-up clarifications on a research brief within the same session

**Telegram Output**
- Summary delivered inline in Telegram (2–4 paragraphs)
- Full brief committed to `research/[ticket-id]-[slug].md` and linked in the Linear ticket

### 3.4 Developer

The most complex agent. Picks up Linear tickets each morning and implements them autonomously. Accepts direct tasks via `/dev` command. Free-form conversational dev requests are intentionally routed through the Manager first to maintain Linear traceability and cost predictability.

**Why Developer Skips Free-Form Routing**
- Developer runs are the most expensive per invocation (Sonnet + Claude Code)
- Tasks without a Linear ticket are invisible to the Manager's daily digest and log tracing
- The Manager can fast-track small tasks directly to the Developer after ticket creation, keeping overhead minimal
- Use `/dev` to bypass this when you want direct, immediate execution without a ticket

**Daily Morning Job**
1. Read Linear board. Find highest-priority ticket in 'Ready' assigned to Developer's GitHub account.
2. Read ticket and any linked research brief.
3. Create branch: `feature/[ticket-id]-[slug]`
4. Implement using Claude Code.
5. Run test suite. Attempt fixes if failing (up to 3 retries).
6. Open PR with description, testing notes, Linear link, and screenshots if UI changes.
7. Update Linear ticket to 'In Review'.
8. Send Telegram notification: PR URL, test results summary, any concerns.
9. Write log entry to observability store.

**Agentic QA Feedback Loop (V2)**
- GitHub Actions CI on every PR: lint, unit tests, integration tests, Claude review bot
- CI failure → webhook → Developer reads error, attempts fix (max 3 attempts)
- After max retries: Telegram alert to Sam with error context and PR link

---

## 4. System Architecture

### 4.1 Orchestration Layer

Two always-running Python processes on the Raspberry Pi, managed by systemd services:

- `scheduler.py` — APScheduler running all cron jobs: PA Friday meal plan, Manager 9am digest, Developer morning pickup, Manager weekly prompt review
- `bot.py` — Telegram bot in long-polling mode, handling all inbound messages, running the router for free-form messages, managing per-agent conversation context, and routing to agent handlers

Both processes import from a shared `agents/` package containing the Claude API client, the message router, conversation context manager, logging utilities, and integration helpers for Linear, GitHub, and Drive.

| Component | Responsibility |
|---|---|
| Raspberry Pi + APScheduler | Cron-style triggers for all scheduled agent jobs |
| Raspberry Pi + python-telegram-bot | Long-polling bot, command routing, free-form routing, inline button handling |
| Message Router (Haiku) | Classifies free-form messages to the correct agent; returns `clarify` on low confidence |
| Conversation Context Manager | Rolling 10-message window per agent per chat; 30-min inactivity reset |
| GitHub (private ops repo) | Living system prompts, logs, research briefs, prompt proposals |
| Linear API | Ticket read/write for Manager and Developer |
| Google Drive API | Permanent output storage: meal plans, research briefs, digests, ideas inbox |
| Telegram Bot API | Primary human-agent communication: conversation, commands, reports, approvals |
| GitHub Actions | CI/CD, automated testing, Claude review bot on every PR |
| Claude API | All inference — Sonnet for Developer/Researcher, Haiku for PA/Manager/Router |
| Vercel | Frontend deployment (triggered by Sam-approved merges only) |
| Claude Cowork | Secondary interface for longer review sessions |

### 4.2 Router Implementation

The router is a single Claude Haiku call with a tightly scoped system prompt. It receives the incoming message text and returns a JSON object: `{ agent: string, confidence: float, reason: string }`. The bot uses the confidence score to decide whether to route automatically or show clarification buttons. Threshold for auto-routing is 0.75.

| Confidence | Threshold | Behavior |
|---|---|---|
| High | >= 0.75 | Auto-route to agent, show attribution prefix in response |
| Low | < 0.75 | Send inline clarification buttons before proceeding |
| Developer route | Any confidence | Always route to Manager first unless `/dev` was used explicitly |

### 4.3 Living System Prompts

Each agent's behavior is governed by `agents/[agent-name]/system-prompt.md` in the ops repo. Both `scheduler.py` and `bot.py` load this file fresh on every agent invocation. The Manager's weekly job proposes diffs via Telegram inline approval; changes merge to the ops repo only after Sam approves.

### 4.4 Model Selection & Cost Management

| Component | Model | Rationale | Est. Monthly Cost |
|---|---|---|---|
| Developer | claude-sonnet-4 | Complex reasoning, code quality | ~$20–25 |
| Researcher | claude-sonnet-4 | Deep analysis, web search | ~$5–8 |
| Manager | claude-haiku-4-5 | Structured data ops, low complexity | ~$2–4 |
| PA | claude-haiku-4-5 | Conversational + structured tasks | ~$2–4 |
| Message Router | claude-haiku-4-5 | Single classification call, very low token count | < $1 |
| Infra (Pi) | — | Electricity only | ~$2 |
| **Total** | | | **~$32–44/mo** |

---

## 5. Observability & Logging

### 5.1 Log Schema

Every agent run produces a structured JSON log entry at `logs/YYYY-MM-DD/[agent]-[run-id].json` in the ops repo:

| Field | Type | Description |
|---|---|---|
| `run_id` | string (uuid) | Unique identifier for this agent invocation |
| `agent` | string | `pa \| manager \| researcher \| developer \| router` |
| `trigger` | string | `scheduled \| telegram_command \| telegram_freeform \| webhook` |
| `triggered_at` | ISO 8601 | Timestamp of invocation |
| `task` | string | Human-readable description of the task |
| `telegram_input` | string \| null | Original message text from Sam, if applicable |
| `router_decision` | object \| null | `{ agent, confidence, reason }` from router, if free-form |
| `linear_ticket` | string \| null | Ticket ID if applicable (e.g. ENG-42) |
| `steps` | array | Ordered list of steps taken with reasoning and tool calls |
| `output` | object | Final output: PR URL, Drive link, Telegram message ID, etc. |
| `status` | string | `success \| flagged \| failed` |
| `tokens_input` | integer | Input tokens consumed |
| `tokens_output` | integer | Output tokens consumed |
| `cost_usd` | float | Estimated cost of this run |
| `duration_seconds` | integer | Wall-clock time for the run |

### 5.2 /logs Telegram Command

The `/logs [n]` command pulls the last n log entries and returns a plain-English Telegram summary: what each agent did, what succeeded, what got flagged, router decisions, and the running monthly cost total.

### 5.3 Observability Dashboard (V3 Dog-food Project)

A Next.js dashboard deployed to Vercel reading JSON logs from the ops repo via GitHub API:

- Filterable, searchable activity timeline across all agents
- Router decision log — shows what was auto-routed, what was clarified, and routing confidence over time
- Per-agent run history with expandable step-by-step decision traces
- Cost tracking by agent and by week, charted against the $50 budget
- PR status tracker — all open agent-authored PRs with CI and review status

---

## 6. GitHub Setup & Code Quality

### 6.1 Agent GitHub Accounts

| Account | Permission Level | What It Can Do |
|---|---|---|
| sam-agent-developer | Write | Push branches, open PRs — cannot merge |
| sam-agent-manager | Read + Issues | Read repos, comment on PRs, update Linear |
| sam-agent-researcher | Read | Read repos, commit research briefs to ops repo |

### 6.2 Branch Protection Rules

- `main` requires at least 1 approved review (Sam only) before merge
- All status checks must pass: lint, tests, and Claude review bot
- No direct pushes to `main` — all changes go through PRs
- Delete branch on merge enabled

### 6.3 GitHub Actions CI Pipeline

- Lint: ESLint / Prettier for JS/TS, Ruff for Python
- Unit tests: Jest for frontend, Pytest for Python
- Integration tests: Playwright for UI (V2+)
- Claude review bot: structured code review comment on every PR
- Agentic QA loop: CI failure → webhook → Developer self-correction (max 3) → Telegram alert (V2)

---

## 7. Phased Rollout Plan

### Phase 1 — Foundation (Weeks 1–3)

Goal: Core infrastructure running. Telegram bot live with commands and free-form routing. PA and Manager delivering scheduled outputs. Developer opening basic PRs.

| # | Task | Description |
|---|---|---|
| 1 | Ops repo setup | Private GitHub repo for system prompts, logs, research, digests |
| 2 | Logging schema | JSON log schema and log writer utility |
| 3 | Pi scheduler | APScheduler + systemd service + health check endpoint |
| 4 | Telegram bot — core | Bot process, user ID allowlist, slash command routing, inline button handler |
| 5 | Message router | Haiku-based classifier for free-form messages; confidence threshold + clarify buttons |
| 6 | Conversation context manager | Per-agent rolling context window, 10-message limit, 30-min inactivity reset |
| 7 | PA — meal plan + conversation | Friday meal plan job + free-form conversational responses via Telegram |
| 8 | Manager — daily digest | Linear API integration, 9am digest delivered to Telegram |
| 9 | Manager — /plan skill | Plain-English → Linear ticket proposals with Telegram inline approval |
| 10 | Developer — basic PR | Linear read, Claude Code implementation, PR opened, Telegram notification |
| 11 | /status and /logs commands | Instant board summary and log tail in Telegram |

### Phase 2 — Autonomy (Weeks 4–8)

Goal: Developer fully autonomous on git. CI/QA pipeline live. Researcher agent added.

| # | Task | Description |
|---|---|---|
| 12 | Developer GitHub account | sam-agent-developer with Write access to repos |
| 13 | Autonomous git operations | Branch creation, commit, push, PR open via GitHub API |
| 14 | GitHub Actions CI | Lint + test pipeline on all PRs |
| 15 | Claude review bot | Automated structured PR review comment on every PR |
| 16 | Agentic QA loop | CI failure webhook → Developer self-correction (max 3) → Telegram alert |
| 17 | Researcher agent | On-demand brief generation, conversational follow-up, summary to Telegram + Drive |
| 18 | Manager — prompt proposals | Weekly PR pattern analysis → prompt update proposals via Telegram |
| 19 | Manager — ideas inbox | Drive ideas.md watcher → ticket proposals → Telegram approval flow |

### Phase 3 — Full Vision (Month 3+)

Goal: Polished observability dashboard, multi-agent coordination, production-grade autonomous output.

| # | Task | Description |
|---|---|---|
| 20 | Observability dashboard | Next.js app reading log JSON, deployed to Vercel — first dog-food project |
| 21 | Router analytics | Dashboard view of routing decisions, confidence distribution, misroute patterns |
| 22 | Playwright UI testing | Automated visual + interaction tests on all frontend PRs |
| 23 | Multi-agent coordination | Manager ↔ Researcher ↔ Developer handoff without Sam involvement |
| 24 | PR quality gates | PRs surface to Sam only when tests pass AND Claude review score ≥ threshold |
| 25 | PA expansion | Drive organization, expanded life task templates, proactive suggestions |
| 26 | Cost optimization | Automated model routing based on task complexity and remaining monthly budget |

---

## 8. Integrations & Credentials

All credentials stored as environment variables on the Pi. Never committed to any repository. A `.env.example` documents all required keys without values.

| Integration | Auth Method | Used By |
|---|---|---|
| Claude API | API Key | All agents + message router (inference) |
| Telegram Bot API | Bot Token (from @BotFather) | bot.py on Pi — all human-agent communication |
| Linear API | Personal API Key | Manager, Developer (ticket read/write) |
| GitHub API | Per-agent Personal Access Token | Developer (code), Manager (PR comments), Researcher (briefs) |
| Google Drive API | OAuth 2.0 Service Account | PA (meal plans), Manager (digests, ideas inbox) |
| Vercel API | API Token | Manager (deployment status monitoring) |

---

## 9. Success Metrics

| Metric | V1 Target | V3 Target |
|---|---|---|
| Weekly meal plan delivered via Telegram without prompting | ✓ Every Friday | ✓ Every Friday |
| Daily manager digest in Telegram by 9am | ✓ Every day | ✓ Every day |
| Free-form messages routed correctly without clarification | > 70% | > 90% |
| PA follow-up questions understood in context | ✓ | ✓ |
| Developer picks up ticket and opens PR autonomously | Manual assist OK | Fully autonomous |
| PRs pass CI on first attempt | Not measured | > 70% of PRs |
| Total monthly spend | < $50 | < $50 |
| All agent runs have searchable logs | ✓ | ✓ + dashboard |
| Telegram command to first agent response | < 60 sec | < 30 sec |
| Time Sam spends on ticket management per week | < 30 min | < 10 min |

---

*This PRD is a living document. The Dev Manager agent will propose updates as the system evolves. All proposals are delivered via Telegram for Sam's approval before any changes take effect.*
