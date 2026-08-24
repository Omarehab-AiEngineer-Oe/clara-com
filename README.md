# Clara Competitor & Pricing Intelligence

Implements `Clara_Centric_Autonomous_Competitor_Intelligence_Agent_Requirements.docx`
(rev 3.0) **and** `Competitor_Intelligence_Requirements_Addendum.docx`.

The addendum changed what this project is. It used to be a collection pipeline that
produced a long report; it is now an **operational web application** with the
pipeline behind it. The report was something you read. The application is
something you work in: an ambiguous match is resolved on its own page, a source
that cannot be read becomes a task with the controls that fix it, a question you
cannot answer becomes a request that reaches a person, and every change carries
who made it, when, and what it replaced.

```bash
python serve.py                       # the application: http://127.0.0.1:8770
python run_agent.py --run-id r2       # collect (slow; contacts competitor sites)
python ops_import.py --run-id r2      # fold that run into the operational store
python ops_import.py --status         # what the operational store holds
python tests/test_addendum.py         # the addendum's acceptance criteria
```

## The five tabs (addendum §3)

| Tab | What it is for |
|---|---|
| **Overview** | Freshness, coverage, unresolved actions, verified price movements, active offers, request attention — every figure links to the records it counts. |
| **Products** | The Clara catalogue: assigned competitors, match status and confidence, prices, availability, freshness, provenance, attention state. |
| **Competitors** | The directory: their products, source coverage, observed prices, offers, commercial profile, approved sources, change history. |
| **Actions** | The work queue. Ambiguous matches, unreadable sources, stale prices, missing data, failed verifications — each resolved **in place**. |
| **Requests** | Questions raised for a person. Eight types, five statuses, and the record they came from attached. |

Around those five, per §3.1:

- **Product and competitor pages are routable** — `/products/<id>`,
  `/competitors/<key>`. Not modals. A modal cannot be linked, so it cannot be an
  Overview shortcut, the subject of a request, an agent citation, or a bookmark.
- **The Agent is a header control** opening a right-side panel, so it inherits
  whatever record you are reading rather than asking which one you meant.
- **Send Request** is a header action and a contextual action on every supported
  record, prefilled from that record.
- **Offers** are contextual, with `/offers` as an optional filtered view. Not a
  main tab.
- **Users, Request administration, Sources & feeds, Audit history and System**
  live in an **Admin** menu, not the business navigation.

### Retired and separated

| Was | Now |
|---|---|
| `/decisions` — pricing, product, sales, trend and marketing recommendations in one list | **Retired** (§2). Competitor findings are on Overview and in Actions. The route redirects and says why. |
| `/` — one long page with every product, competitor, offer and task | **Retired as the product** (§2). Still readable at `/report` as a migration aid. |
| `/trends` — Beauty Trends, inside the same navigation | **Separated** (§3.1). A distinct optional module: `python serve.py --with-trends`, or `CLARA_WITH_TRENDS=1` when hosted. Not part of Competitor Intelligence. |
| Reports as the operational output | **Exports, not the system of record** (§1). `/prices.csv` and `/prices.jsonl` remain; the database is the source of truth. |

## Actions are resolved in the application (§4)

This is the change the addendum was written for. The old behaviour was a report
section listing what someone ought to go and do, with an outbound link and a
paragraph of instructions — which §2 names as no longer appropriate.

**Ambiguous matches (§4.2)** offer five outcomes: pick a candidate, supply a
different URL, confirm the counterpart, mark *No counterpart*, or add a note.

**Unreadable sources (§4.3)** offer eight: choose an approved alternative, enter a
new URL, request verification, enter the value by hand, select or register an
approved feed/API, mark the source unavailable with a reason, or add a note.
Manual entry takes all six fields §4.3 lists, with **observed** and
**last-checked** kept separate — you may be recording a price you read on Tuesday
and re-checked today.

**One transaction, always.** A resolution writes the domain change, the action
transition and the audit event together or not at all. `Db.exec` refuses to run
outside a transaction, so the atomic-save rule is a constraint rather than a
convention. A rejected resolution leaves nothing behind — there is a test for
exactly that.

**The page renders only valid options, and the server checks again.** Both read
one list. An option your role cannot perform is shown *disabled with the reason*,
because hiding it teaches you it does not exist, while "marking a source
permanently unavailable is an admin operation" teaches you who to ask.

## The Agent explains; it does not advise (§6, §7)

Read-only, grounded in stored records, and scope-limited. It explains matches,
prices, differences, offers, availability, provenance, freshness, confidence, who
confirmed what, and what is still open.

It does **not** do marketing campaigns, advertising, SEO, social media,
copywriting or customer acquisition. §1 removes those from this module so that
everything the agent says can be traced to a stored observation.

The implementation is **deterministic** — there is no generative model in the
path. That makes §12's "no marketing behaviour" criterion a property of the
architecture rather than a hope about a prompt. The scope check still runs twice,
on the question and on the answer, so a future model-backed path cannot ship
drift. The contract is written out in
`prompts/agents/competitor_intelligence_assistant.md`.

When the evidence does not reach, the agent says which way it fails — missing,
stale, inaccessible, conflicting or insufficient, because those call for
different actions — and offers **Send Request**. The request carries the
conversation summary, the citations and the missing-evidence explanation,
assembled from the stored conversation rather than retyped.

## Provenance and audit (§8)

Every displayable value carries one of four labels, and the column is `NOT NULL`
with no default, so forgetting it is a constraint violation rather than a blank
badge:

| Label | Meaning |
|---|---|
| Automatically observed | Collected by an approved run from the cited source. |
| Human-confirmed | A person reviewed evidence and confirmed it. |
| Manually entered | A person entered it directly; actor, note and date required. |
| Approved feed/API | From an administratively approved integration. |

**Corrections never erase.** A correction appends a new observation or match
version and marks the old one superseded; both stay on the page with their own
provenance. There is no UPDATE path in the schema that overwrites an observed
value.

**Audit is append-only.** 8.1's field list is the column list, and no statement
anywhere in `ops/` updates or deletes an audit row — checked by parsing the
source, not by grepping it.

## Persistence (§9)

Operational data must survive restarts, instance recycling and redeployment.

```bash
DATABASE_URL=postgres://…  # every operational write goes to managed Postgres
                           # unset: the local SQLite file, correct for local work
```

One data layer speaks both dialects. The same SQL runs on both because the schema
avoids everything they disagree about — no serial types, no `RETURNING`, no upsert
syntax, no JSON operators. Keys are generated in Python, JSON is stored as text,
timestamps are ISO strings.

**A hosted deployment without `DATABASE_URL` says so** — on the System page and in
a banner on every page. §2 lists a silent fallback to instance-local files as no
longer appropriate, and a reader who cannot see that their resolution is about to
be discarded has been misled.

### Running locally on Postgres

Worth doing before any deploy: the dual-dialect layer only gets exercised on the
engine that matters if you run it there. Two Postgres-only bugs were found this
way — a `? IS NULL` comparison Postgres cannot type, and a literal `%` in SQL
that psycopg reads as a placeholder. Both worked perfectly on SQLite.

```bash
docker compose up -d                 # PostgreSQL 16 on 127.0.0.1:55432
export DATABASE_URL=postgresql://clara:clara_local_dev@127.0.0.1:55432/clara_ops
pip install "psycopg[binary]"
python ops_import.py                 # builds both schemas, folds in the last scan
python ops_import.py --status        # should print: durable  yes
python serve.py                      # the banner is gone
```

Both acceptance suites run against whichever engine `DATABASE_URL` selects, so:

```bash
DATABASE_URL=postgresql://... python tests/test_addendum.py    # 116 checks
DATABASE_URL=postgresql://... python tests/test_audit_prd.py   # 112 checks
```

Durability is testable rather than asserted: resolve an action in the UI, stop the
server, restart it, and the resolution, its match version and its audit event are
still there.

**An import never overwrites a human decision.** A match somebody confirmed stays
confirmed; where a scan disagrees, an Action is raised instead — which is the
correct outcome, because a scan contradicting a person is exactly the thing a
person should look at. Importing the same run twice does nothing the second time.

## Roles (§9.2)

Enforced on the server, at the operation — hiding a control in the UI is
insufficient, so the UI hides it *as well*, never *instead*.

- **User** — resolves actions, corrects matches, enters observations by hand,
  replaces sources, requests verification, asks the agent, raises requests. §12's
  first criterion is that *a user* can resolve an ambiguous match, so resolution
  is not an admin power.
- **Admin** — additionally: assigns and dismisses actions, owns and answers
  requests, approves sources and feeds, marks sources unavailable, manages users,
  reads the audit history.

## Tests

```bash
python tests/test_addendum.py     # the addendum's criteria         (116 checks)
python tests/test_pages.py        # the legacy report and trends pages (66 checks)
python tests/test_discovery.py    # source discovery                  (55 checks)
python sync_deploy.py             # rebuild the bundle and verify it   (71 checks)
```

`test_addendum.py` runs against a real database seeded from the real collection
store, exercising the real importer, resolution handlers, transaction boundary and
router. Nothing is mocked — a test passing against a stub would only tell us the
stub is correct.

## Hosting

```bash
python run_agent.py --run-id r3        # collect, locally
python ops_import.py --run-id r3       # into the operational store
python sync_deploy.py --deploy         # rebuild the bundle, verify, push
```

Collection cannot happen inside a serverless request — it contacts competitor
sites for about an hour and is bound by the access policy — so it stays a local
job and the result is imported. The hosted instance serves live operational data
over a snapshot of collection, and the System page states both separately, because
conflating them is how "the data is old" and "your work was lost" get mistaken for
each other.

Accounts remain local: they live in the bundled snapshot, so a hosted change would
be written to one instance's temporary filesystem. The Users page is read-only
there, with the reason stated, rather than offering buttons that discard the
change. Everything else is fully writable against Postgres.

## Approval gate (§13)

§13 requires approval of the five-tab navigation, the retirement of the mixed
Decisions tab, the separation of Beauty Trends, the MVP boundary, the request
workflow, the agent scope, the provenance model and the PostgreSQL direction
before implementation. This tree implements all of them; the gate is a review of
what is here, not a question still open in the code.

---

# The collection layer

Everything below describes how the evidence is gathered — the part the addendum
did not change. The application above is what consumes it.

## The legacy report

`/report` still renders the old long page, read-only, so nothing that was on it is
lost while the five tabs bed in. It is not the product any more.

# Beauty Trends Intelligence — a separate optional module

Separated from Competitor Intelligence by addendum §3.1. It is not served
unless you ask for it (`python serve.py --with-trends`, or
`CLARA_WITH_TRENDS=1` when hosted), and it does not appear in the
application's navigation. Everything below still applies to it.


`/trends` — an early-warning feed for the beauty market, rebuilt from live
sources on every scan.

    python run_trends.py        # fetch every registered feed
    Scan now                    # the same thing, from the page

**There is no curated trend list any more.** There is a registry of sources in
`clara_monitor/trend_sources.py` and a collector in
`clara_monitor/agents/trend_collector.py`. Run a scan and the page changes,
because the sources changed.

## Why feeds, and only feeds

A publisher that ships RSS is inviting automated reading, which is the exact
opposite of a login-walled platform. That makes feeds the one surface where
continuous collection is both possible and clearly permitted, so it is the only
surface used. Every fetch goes through `access.guarded_get`.

Two kinds of source, proving different things:

| kind | what it is | what it proves |
|---|---|---|
| `search_demand` | Google Trends rising queries, per country | what people typed |
| trade / consumer / retail press | 11 publisher feeds | what the industry is being told, and why |

**24 feeds answer. 8 refuse and 4 are dead**, and the page names all twelve with
the reason — Byrdie, Happi and Arab News return 403; Reddit is `robots_disallowed`;
the four Cosmetics Design feeds return 404/410. A scan that silently omitted them
would look identical to a market where nothing happened.

## Stage is measured, not assigned

Nothing is computed from a single scan. Signals are stored insert-once keyed by
URL, and every topic is recomputed across everything ever collected — which is the
only scope in which "rising" and "declining" mean anything:

| stage | what was measured |
|---|---|
| emerging | one or two publishers, all recent |
| rising | several publishers, and this week heavier than the weeks before |
| viral | many publishers inside a short window |
| mainstream | sustained across many publishers over a long span |
| declining | nothing new for a long time |

Each card prints the reason: *"6 item(s) in the last week against 1 before it,
across 5 publisher(s)"*. That measures **attention, not sales** — the page says so,
because inferring commercial success from press coverage is the most common way a
trend report becomes confidently wrong.

## Three timestamps, because one blurs three facts

    first seen      when the subject first appeared in anything we read
    last confirmed  when the last scan still found evidence
    last changed    when the picture actually moved

A topic re-confirmed today with nothing new is not the same as one that gained
four publishers today. Each is shown as a relative clock with the absolute day in
the tooltip, so "3 days ago" can always be checked against
"Mon 18 Aug 2026, 09:14 UTC".

Proven by running twice: scan 2 read the same 24 feeds and added **0 new signals**,
reporting "nothing moved" — which is deduplication and comparison working, not a
failure.


## The trends page: cards, then a popup

    scan the grid -> a card looks interesting -> open it -> understand it
    -> close -> keep scanning

Cards stay short enough to scan a screenful; the popup carries the depth. Nothing
that belongs in the popup is allowed onto a card, because a grid of paragraphs is
a list nobody reads.

**A card carries** icon · stage · freshness badge · confidence · title · a
three-line description · up to three tags · momentum arrow · when it last moved ·
*View details →*. Grid is 4 columns, 3 under 1240px, 2 under 900px, 1 under 600px.

**The popup carries** why it is trending (with the arithmetic) · reach · what an
agent can do with it · example workflows · how to implement it · every headline
with its link and date · sources with when each feed was checked · how it has
moved · freshness · related trends · a *Build with my agent* link to the decisions
page.

**Two kinds of content, never blurred.** The market half — stage, momentum,
publishers, markets, evidence, dates — is derived from what was fetched. The
capability half — what an agent can do, workflows, how to implement — is this
system's own playbook, and the popup says so in a marked block above the first
one. A reader who cannot tell which half is measured has been misled, however
useful the suggestions are.

**Badges are real or absent.** `NEW` is first seen inside 48 hours; `UPDATED` is
moved inside a week. Both come from stored timestamps, so a subject that has not
moved carries no badge rather than a decorative one.

**Controls:** search (title, tag, publisher, market) · category · market · stage ·
changed-recently. All narrow the same grid, each is independent, and every chip
shows its count so a dead filter is visible before it is clicked.

**Popup behaviour:** fades in with the sheet easing up; closes on ✕, Escape or
backdrop; Tab is trapped inside; focus returns to the card that opened it; the
page is pinned at its scroll offset so closing returns to the same row; a phone
gets a full-height sheet that is still a modal. `prefers-reduced-motion` drops the
transitions.

**URL state:** `/trends?trend=korean_beauty` opens straight into that trend.
Closing removes the parameter with `replaceState` — no reload — and Back/Forward
move between open and closed.

**Scale:** 12 cards render, the rest behind *Show more*; filters still report the
true total. New subjects appear as cards in the same grid with no page change.

### Freshness is real, not decorative

`first_seen_at` is when the agent actually recorded an item, and re-scanning never
moves it — an item already known keeps its original timestamp. That is what lets
the page tell new intelligence from old, and why the clock reads *12 min ago*,
*2 hours ago*, *yesterday* rather than all showing the same time. A stage change
between scans is appended to `trend_stage_event`, so a trend that moves from
rising to viral keeps the record of when it moved.

### Evidence discipline

Every trend, offer and brand carries its sources with URLs, and each source is
labelled by kind — trade press, brand, retailer, research firm or government.
Confidence is stated per trend, and a trend whose only support is a vendor report
or a trade blog says so. Where evidence cuts both ways the card carries a **what
weakens this** block: the Korea–UAE CEPA trend, for example, notes that reporting
also finds many Korean brands struggle after launch in the region.

Nothing on the page is invented. Figures are the figures the source printed.

### Agent tools

`get_beauty_trends(market, stage, category)` and `compare_beauty_markets()` are
exposed to the ADK agent alongside the competitor tools, so the model can read the
trend store directly.


---

## The central operating model (§4)

Product-first, and discovery is unreachable except through a failed validity test:

```
for each Clara product:
  1 load product + assigned competitors      catalog.py / competitors.py
  2 read stored matches                      store.get_matches_for_product
  3 REFRESH valid matches first              engine.process_pair
  4 revalidate identity (fingerprint drift)  matching.fingerprint_drift
  5 discover ONLY if missing/invalid         discovery.DiscoveryChain
  6 evaluate candidates                      engine.score_candidate
  7 classify with score + evidence           engine.classify
  8 collect price/stock/variants/images      extract.extract
  9 validate + normalize                     extract.validate
 10 store match + observation + history      store.py
 11 report + escalate                        reporting.py
```

`store.match_is_valid()` is the gate. A match is refresh-only when it is
`confirmed_match`/`probable_match`, inside `ttl_days`, still resolves, still
fingerprints to the same product, still allowlisted, and has no open exception.

**Verified:** on a second run over the same scope, every valid stored match was
refreshed and only unresolved pairs entered discovery.

## The critical constraint (§2, §19)

Autonomy does not authorize bypassing a login, CAPTCHA, access restriction, site
terms or technical control. This is enforced in code, not left to the prompt:
**every** network read goes through `access.guarded_get`, and there is no second
path. It will not

- fetch a host outside the run allowlist, or a path `robots.txt` disallows
- send credentials, cookies or an `Authorization` header
- vary the User-Agent to look like a different client (one identity, never rotated)
- retry a 401 / 403 / 429 / challenge response by any means
- follow a redirect into a login page and keep going

Each returns `blocked=True` with the signal. The caller's only legal response is
to escalate, and a blocked pair is **never** downgraded to `no_match` or filled
with an assumed price.

Over-blocking is treated as a bug too: a shop that embeds reCAPTCHA on its
newsletter form is not a blocked shop, so ambiguous markers only count when the
page also has no product payload (`_looks_like_a_challenge_page`).

Retries (§17) are bounded to 3, temporary failures only, exponential backoff with
jitter, `Retry-After` honoured; a host that rate-limits is paused for the run.

## Statuses (§9A)

| Status | Meaning |
|---|---|
| `confirmed_match` | identity proven by identifier or a high-confidence brand/model/attribute combination |
| `probable_match` | evidence strong but not definitive; observations still collected |
| `ambiguous` | two plausible candidates, or material identity conflict — **escalated, never auto-decided** |
| `no_match` | nothing met the threshold after bounded discovery; outcome retained |
| `invalidated` | a stored match failed identity/URL validation; history kept, re-discovery triggered |
| `blocked` | site refused or challenged — **escalated, not downgraded** |

Two rules that shape the numbers you see:

- **Price is never identity evidence.** The score has no price term at all.
- **Specification differences are findings, not conflicts.** A rival dryer at
  1400 W where Clara's is 2000 W is still the rival dryer. Only identity
  conflicts (different brand, model line, contradicted identifier, or a model
  judgement of "not the same product") make a pair ambiguous. Conflating the two
  made almost every pair escalate in an early run.
- **Variants are folded, not escalated.** Two colourways of one Airwrap are one
  product's variants (§11), so they are merged before the ambiguity test rather
  than treated as rival candidates.
- `attachment_of_system` is **capped at `probable_match`**: where a Clara device
  maps to one attachment of a modular rival, formats do not fully agree however
  well the specs line up, and the system price and non-separability are stored.

## Money (§11)

Never floating point. `money.py` parses to `Decimal` and keeps the raw text:

- ranges are kept as min/max — never a midpoint
- "from SAR 429" is flagged as applying to the cheapest variant only
- a discount is computed only from a real regular *and* selling price; a sale
  price above the regular price warns and yields no discount
- currency is required alongside any numeric price, and is **never converted**

## Method selection (§9)

The ladder is followed in order and the method plus the reason is recorded on
every observation: JSON-LD structured data → HTTP + HTML parser → permitted public
page API → browser automation. Browser automation is not wired up in this build,
so a page too thin for HTTP extraction escalates rather than storing a thin record
as complete.

Validation (§13) is deterministic: `accepted` / `accepted_with_warnings` /
`rejected`. Confidence is supporting metadata, never a substitute.

## Vertex AI

Identity judgement is model-assisted via Gemini on Vertex AI, pinned to the
`global` location (`llm.py`, and `GlobalGemini` in `agent.py`). The model judges
*identity only* and is bounded by the deterministic format gate, per §6
("validation and storage integrity must not depend only on free-form model
judgment"). It never writes a price, a stock status or a stored record.

Every match records its `decision_source` — `vertex_gemini` or
`deterministic_rules` — so a run is auditable back to how each call was decided.
If credentials are missing or expired the Agent falls back to the rules, records
that, and the run continues. `model_status()` probes with one real call rather
than assuming a constructed client means working credentials.

To enable the model path:

```bash
gcloud auth application-default login       # or supply a service account
# optional overrides
setx CLARA_VERTEX_MODEL gemini-3.5-flash
setx CLARA_VERTEX_LOCATION global
```

## Competitors (§7, §20)

**26 competitors** are registered in `competitors.py` across two segments, each
with a tier, a domain allowlist and optional sitemaps:

- **Devices** — Dyson, Shark Beauty, Laifen, ghd, Revlon, BaByliss, Remington,
  Philips, Braun, Panasonic, Dreame, T3 Micro, Drybar, Xiaomi, Kemei, Silk'n,
  Hot Tools, Conair
- **Haircare** — Olaplex, Kérastase, Moroccanoil, L'Oréal Paris, Redken, K18,
  Schwarzkopf, Wella

`competitor_profiles.py` carries the commercial profile for each: origin,
positioning, typical Saudi price band, what it is known for, how it usually
discounts, its audience, and a threat rating with a note on what it means for
Clara. These are **editorial fields maintained by a human**, labelled as such on
the site and stored apart from anything observed.

Assignment is data, not code: `ASSIGNMENT_BY_FORMAT` and
`ASSIGNMENT_BY_CATEGORY` map each Clara product to an ordered competitor set, and
`--targets N` caps how many are evaluated per product per run.

**Classification is name-first.** A shampoo whose page copy mentioned the
multi-styler was being classified as a device and compared against a 2,299-riyal
Airwrap — three false `confirmed_match` rows came from that. The name now decides
segment and category before the description is consulted, an explicit part word
(diffuser, barrel, nozzle) makes something an accessory outright, and a plain
bristle brush is no longer a device. `reclassify.py` applies a corrected
classification to an existing store and retires the pairings it invalidates,
recording a `match_event` for each rather than deleting the trail.

## Discovery (§8)

Conditional, and cheapest-first: curated seeds → the competitor's own sitemap,
keyword-filtered from the Clara product's attributes → Vertex-built queries handed
to the Google Search sub-agent. Every run records the trigger, the queries, the
candidate sources, everything considered and the stop reason. Sitemaps get a short
timeout, no retries and one chance per competitor — they are an optimisation, not
the point of the run.

## Reports (§18)

| Output | Contents |
|---|---|
| **Price report** | **every** Clara product with its price and each matched competitor product and price beside it |
| Coverage report | each product × competitor with status, URL, last validation, observation, evidence |
| Escalation report | blocked and ambiguous pairs with evidence, conflicts and required decision |
| Competitor report | registry with per-status pair counts |
| Exports | `prices_<run>.csv` and `prices_<run>.jsonl`, keyed by Clara product id and run id |
| Website | `reports/site_<run>.html`, rendered from the above |

## Layout

```
prompts/catalog_monitor.md   the Agent instruction (23 sections)
agent.py                     ADK LlmAgent + GlobalGemini; one tool per §4 step
run_agent.py                 manual run command (§16)
clara_monitor/
  access.py       the gate — every read goes through it; retries, pauses, robots
  competitors.py  registry, tiers, allowlist, assignment rules
  config.py       run config, thresholds, scope
  models.py       normalized records + NOT_PUBLISHED
  money.py        Decimal prices, ranges, discounts — no floats
  catalog.py      Clara catalog, format + segment/category + spec extraction
  discovery.py    seed / sitemap / LLM-query providers, bounded and logged
  extract.py      §9 method ladder, §10-12 fields, §13 validation verdicts
  llm.py          Vertex AI judge, probed availability, recorded decision source
  matching.py     fingerprints, drift tolerance, format equivalence
  engine.py       the run loop, change detection, escalation
  store.py        SQLite; history, match_events, errors are insert-only
  reporting.py    price / coverage / change / escalation / competitor + exports
  site.py         renders the website FROM the reports
  cards.py        product + competitor card grids and their detail modals
  competitor_profiles.py  the editorial commercial profile per competitor
  auth.py         users, scrypt passwords, server-side sessions
  pages.py        login and user-management pages
serve.py          local web server behind login: /, /admin, /refresh, /rerun
reclassify.py     apply a corrected classification and retire stale pairings
data/             seed catalog, discovery seeds, monitor.sqlite3
reports/          JSON reports, CSV/JSONL exports, site_<run>.html
```

## Storage guarantees (§15)

- `observation_history`, `match_history`, `match_event`, `change_log`,
  `exception_log` and `error_log` are **insert-only** — no update path exists.
- Replacing an invalidated match never erases why it was invalidated:
  `store.invalidations_for()` keeps the reason after re-discovery overwrites the
  current row.
- A run with no changes records `no_change`. That is a valid run.
- One pair's failure never ends the run; it is recorded and the loop continues.
- §16: overlapping runs for one scope are refused; `--resume` continues an open
  run and skips pairs already completed in it.

## Known limitations, honestly

- **Vertex AI credentials in this environment are expired**, so the run that
  produced the published site used `deterministic_rules` for every decision. The
  model path is implemented and probed; it activates on re-authentication.
- `sharkninja.com` publishes **USD**. The Agent records USD and flags the
  mismatch rather than converting, so those rows are not price-comparable to SAR.
  A Saudi Shark price needs a KSA retailer source added to the seeds.
- `dyson.sa` serves a Cloudflare challenge on some URLs and not others; `noon.com`
  times out and `niceonesa.com` returns 403 for this client. All escalate as
  `blocked` — which is the specified outcome, not a workaround.
- Browser automation (§9 priority 4) is not implemented; pages that need it
  escalate.
- Format and category classification is pattern-based. A competitor product whose
  format cannot be read stays `unknown` and is disqualified rather than guessed.
- §29 asks for precision/recall against a labelled benchmark. No labelled set was
  supplied, so no accuracy claim is made here — `data/candidate_seeds.json` is the
  start of a fixture set, not a benchmark.

## Not built (deliberately, per §3 and §26)

Microservices, queues, autoscaling, dashboard, public API, multi-user admin,
CAPTCHA/login/paywall bypass, predictive pricing, warehouse or event streaming.


Three pages, each with its own treatment:

| page | what it answers |
|---|---|
| `/` — *Clara vs. the competition* | what every product costs, and what the rival costs beside it |
| `/trends` — *What the market is talking about* | what is moving, in the six named markets, from live feeds |
| `/decisions` — *What to decide, and why now* | every call waiting on a person, from both of the above |

Decisions used to sit at the bottom of the competitor report, which put the output
of the whole system below three sections of input. It is a peer page now.
`intel_sections.decision_items` builds the list as plain data and
`decisions_page` owns the layout, so the same list feeds a tile count and a card
without the two drifting apart.

The competitors page carries one offers section, not two. The lifecycle version
— ACTIVE / CHANGED / EXPIRED / UNKNOWN — replaced the older list-everything one
and kept its name, gaining the against-Clara line the old cards had. The discovery
watchlist and the closing footer paragraphs were removed from the page at the
operator's request; discovery still runs and still records what it finds in
`reports/intel_*.json`.


====================================================================
The research team: six agents and one executive report
====================================================================

    python run_research.py         # report from stored evidence, ~1 second
    http://127.0.0.1:8770/          # six sections on the competitors page
    /research.md  /research.json    # the whole report as a file

The research had its own page briefly and no longer does: it lives as six
sections at the bottom of the competitors report, because the research and the
monitoring answer the same question and splitting them made a reader join them by
hand. Four sections of the old page were dropped rather than moved — Clara's
portfolio, best offers, recommended actions and the product comparison — because
this page already answers each one, and a second answer is a second count of the
same thing.

Six came across: the gap register, small competitors, large competitors, a flat
competitor price table, recent news, and threats with opportunities.

| agent | answers |
|---|---|
| Competitor Discovery | who competes, from where, at what observed presence |
| Clara Product & Pricing | the full catalogue, priced from Clara's own storefront |
| Competitor Pricing & Offers | what rivals charge and what they are running |
| Competitor News | dated activity from published sources |
| Offer & Negotiation | advertised terms, kept apart from openings |
| Competitive Comparison | threats, cheapest rivals, opportunities |

## Middle East coverage

The registry was weighted toward Western premium brands, which is not who Clara
loses a Riyadh sale to. Thirteen regional competitors were probed and added — 46
total, all with profiles:

**Value appliance brands, the floor Clara is priced against from below:** Sokany,
Sanford, Nikai (Gulf) and Arzum, Fakir, Sinbo, Goldmaster, King (Türkiye). None
was tracked before, so the report could see the ceiling and not the floor.

**Regional haircare:** Beesline (Lebanon), Dabur — which owns Vatika, the
highest-volume hair-oil brand in the region — Bioblas (Turkish anti-hair-loss),
Nivea, and Huda Beauty as the largest Gulf-born beauty house.

Huda Beauty carries **empty segments on purpose**: it sells no hair tool and no
haircare, so it competes for beauty spend rather than shelf space, and marking it
`device` would drag it into price comparisons where it does not belong.

Refused, and worth knowing: **every Gulf retailer probed said no** — Nice One and
Danube 403, Lulu and Basharacare CAPTCHA, Extra login-required, Nahdi and Faces
404. That layer is where a foreign brand's SAR price would be readable, and it is
closed to us.

## Every field says how it is known

    OBSERVED         read from a real page, with a URL and a timestamp
    EDITORIAL        written by a person; this system did not verify it
    NOT_ESTABLISHED  nothing held — named as a gap with the fix beside it

The page prints the badge rather than footnoting it, because the interesting
question about a competitive report is never what it says but which parts are load
bearing. Nothing is promoted on the way through: a field that arrives EDITORIAL
prints EDITORIAL, including in the executive summary.

**There is no code path that produces** a revenue estimate, a market-share figure,
a negotiated discount, or a price for a competitor whose page was never read. So
no run can accidentally report one. Competitor scale is reported as *observed
presence* — surfaces registered, pages read, Clara products faced — and true
market size is marked not established with the reason.

## The gap register comes before the findings

Every instinct says lead with what was found; every report that does gets quoted
as complete. The current run flags five gaps, each with its command:

- **30 of 33 competitors have no observed price** → `python run_agent.py --targets 8`
- **No advertised discount could be verified.** 13 promotions were read and none
  printed a before-price, so every percentage is the retailer's claim rather than
  a measured saving. The report says `none` in that column.
- **30 competitors appear in no news item** — the feeds are beauty-market press,
  not company newsrooms, so silence means nothing was read
- **54 Clara products face no matched rival**
- **No revenue or market-share figure anywhere**

## What the run found

81 Clara products, 22–770 SAR, banded by segment. 27 comparable pairs resting on
**3 distinct rival products** — grouped by the rival product, because one Dyson
page matched against 24 Clara bundles is one comparison repeated, not 24
findings. Clara is cheaper in 10 same-currency pairs; the Shark pairs are marked
not comparable because Shark publishes USD and currency is never converted.

Negotiation openings are separated from advertised offers and each names what
would confirm it. Six categories the spec asked about — volume discounts,
enterprise pricing, free trials, extended terms, annual commitments, switching
discounts — are marked not applicable with the reason, because these are one-off
physical products with no plans or contracts.

====================================================================
The competitor-intelligence agent layer
====================================================================

    python run_intel.py                  # one cycle from stored evidence
    python run_intel.py --live-discovery # also read brand index pages
    http://127.0.0.1:8770/intel          # the page it produces

Seven specialists under one orchestrator, each with a written instruction in
`prompts/agents/` and a deterministic implementation of the same contract in
`clara_monitor/agents/`. The prompt on disk is the prompt the agent runs — there
is no second copy embedded in the code to fall out of step.

    discovery -> collection -> offers -> diff -> verification
              -> intelligence -> actions -> arrangement -> new state

Verification sits between the diff and the analysis on purpose. Before the diff it
would re-check hundreds of unchanged facts every cycle; after the analysis the
threat assessment would already have been written from unproven claims.

## The state is computed, never copied

    new state = previous state + new evidence + verified changes - what expired

The previous state is a real stored snapshot, not whatever happens to be in the
live tables. A value that survives a cycle is stamped `carried_from` and goes
`stale` once nothing re-confirms it, so an old figure is visibly old rather than
quietly presented as current. Proven by running twice: cycle 1 recorded 26
competitors and 2 offers as the baseline; cycle 2 reported **zero changes**, which
is the correct answer and the only way to tell comparison from recomputation.

## Offers: EXPIRED and UNKNOWN are different facts

An old offer is never carried forward as live. Every cycle re-derives status from
what was actually seen:

| what happened | status |
|---|---|
| seen again, unchanged | ACTIVE |
| seen again, different terms | CHANGED (previous kept for the diff) |
| **page read cleanly, offer gone** | **EXPIRED** |
| **page could not be read** | **UNKNOWN** |
| promo wording, no readable price | UNVERIFIED |

Only ACTIVE and CHANGED reach "Live Competitor Offers". Marking an offer expired
because a site blocked the crawler would invent a competitor's pricing decision
out of a network failure — ten lifecycle checks cover exactly this.

## What the layer refuses to do

- **Never upgrades weak evidence.** `Confidence.never_upgrade` only ever lowers;
  the Verification Agent is the sole path upward, capped by its own verdict.
- **Never merges two competitors on a guess.** Domain is decisive, name is strong,
  a shared product only corroborates — a brand and its retailer share products and
  must not become one record. Anything in between goes to a person unresolved.
- **Never invents a missing value.** Absent fields are the literal `"unknown"`, so
  a gap reads as a gap rather than as an empty string that looks like a value.
- **Never writes a generic action.** An action needs a number, an object, a verb
  and a link, or it is not produced. An empty Actions list is a real result.
- **Never prices an incoherent pairing.** Both sides are re-classified first;
  mismatches are reported on the page rather than silently computed.

## Two real defects this layer found on its first run

1. `match.rejected` holds a JSON list of reasons, not a flag, so the long-standing
   `rejected=0` filter matched nothing.
2. An 89 SAR *2-in-1 Conditioner & Leave-In* was classified `segment=device`
   because `classify_format` reads "2-in-1" as a multi-styler — and that
   misclassification had produced a `confirmed_match` at score 1.0 against a Shark
   FlexStyle. Fixed with a consumable-noun rule that yields to an actual device
   noun, so bundles like "Multi-Use Hair Dryer, Repair & Protection" stay devices.
   25/25 classification cases pass; `reclassify.py --apply` retired 2 false
   pairings.

## Not yet supplied

The operator wrote the prompts for the Orchestrator, Discovery, Data Collection,
Live Offers and Verification agents. The Intelligence, Action and Arrangement
prompts were described rather than written out, so those three files are
reconstructions marked as such at the top. Replacing a file swaps the behaviour
with no code change.

====================================================================
Hosted deployment
====================================================================

    https://clara-price-match.vercel.app        sign-in required

Credentials are not in this repository and should not be. The first admin is
created by `serve.py` on an empty database with a random password printed once to
the console; if it is lost, a new admin is made rather than the old one
recovered. Existing accounts are managed from `/admin/users`.

Both pages are served by `deploy/api/index.py` from the same modules and the same
store as the local server, behind the same sign-in. Nothing on either page is
authored by the deployment.

Four platform facts shape that file, and each is handled rather than hidden:

* **The bundle is read-only.** SQLite writes even to open a database for reading,
  so the snapshot is copied to `/tmp` on cold start and opened from there.
* **Instances are ephemeral and independent.** A session row in `/tmp` would be
  invisible to every other instance and gone on recycle, so a signed-in visitor
  would be logged out at random. Sessions are therefore a signed cookie carrying
  only a username and an expiry, HMAC-verified against a key that is identical on
  every instance and rotates on its own when a password changes. Passwords are
  still checked against the scrypt hashes in the store — that is unchanged.
* **The same reasoning blocks user management.** Adding a user would write to a
  `/tmp` copy nobody else can see. So the Users page is shown **read-only with the
  reason on it**, rather than offering buttons that silently discard the change.
  Add users locally, then redeploy.
* **Requests are short-lived.** A monitoring run contacts competitor sites for
  about an hour and is bound by the access policy, so `/rerun` returns 501 with
  the reason instead of a button that times out.

What is served is a snapshot as of deploy time, and both pages say so. Trend
freshness still counts from each signal's real `first_seen_at`, so the clocks keep
ageing honestly instead of resetting to "just now" on every cold start.

To redeploy after a local run:

    cp data/monitor.sqlite3 deploy/data/ && cp clara_monitor/*.py deploy/clara_monitor/
    cd deploy && vercel --prod
