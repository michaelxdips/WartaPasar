# WartaPasar — Ronce

Ronce is an offline-first editorial engine for IDX market news. It archives provider pages,
replays them deterministically, and turns them into drafts that an editor must review, approve
and preview before anything may be published. It never publishes by itself: live publishing is
off, and the transport layer refuses any write that is not bound to an approved edition.

Bukan nasihat investasi. Seluruh angka di keluaran berasal dari catatan klaim yang ditinjau,
bukan dibaca ulang dari prosa.

## Status

| Area | State |
|---|---|
| Test suite | `python -m unittest discover -q` — 252 tests, all passing (observed 2026-10-02) |
| Live publishing | OFF (`adapters.LIVE_PUBLISHING = False`); every write needs an approved edition, an explicit account, and the live flag |
| Live API | Not exercised in this checkout: `SECTORS_API_KEY` is required and was absent. Archived captures are used instead |
| Social transport | No network transport is implemented in this repository; `adapters.submit` runs a caller-supplied transport after the publication gate passes |
| Web platform | `web/` — static Next.js reader over the export contract; builds and passes the browser smoke harness. Not deployed. |
| Editor workbench | `workbench.py` — private loopback runtime for one local operator; authenticated sessions, engine-gated decisions, no external-release action. Local only, not a deployment |
| Offline outbox | `outbox.py` — durable per-post queue over approved editions; readback-verified completion, no blind retries of ambiguous writes, no network transport |

## What it does

1. **Archive** — `fetch` and `fetch-companion` store provider responses atomically and refuse to
   overwrite an existing archive. `fetch-companion-independent` archives each companion endpoint
   separately so one unavailable endpoint cannot hide the others.
2. **Replay** — `replay` reads archived pages and produces candidates plus a decision trail. It
   never looks past its cutoff; a live edition separates the news window from the moment the
   snapshot finished.
3. **Review** — `review-claims` records editor-reviewed claims. Strict mode binds every number to
   its currency, kind, scale and period in each quoted source, requires distinct sources behind
   distinct origins, and requires opinion text to be labelled and attributed.
4. **Approve** — `render-draft` renders one post per selected reviewed claim; `approve-edition`
   binds the exact texts to an edition and platform; `preview-edition` re-checks text, order,
   provenance and approval and fails closed when anything changed.
5. **Publish gate** — `publication_manifest` exposes the approved posts with their hashes and the
   explicit account; `adapters.publication_preflight` refuses any external write that lacks an
   approved edition, a matching account, or the live flag.

## Quick start

```bash
python -m unittest discover -q          # the whole suite
python ronce.py --help                  # the command surface
```

Offline editorial flow (archives in `draft/`, nothing is published):

```bash
python ronce.py replay draft/news-2026-09-28-direct.json \
  --cutoff 2026-09-28T17:30:00+07:00 --since 2026-09-22T00:00:00+07:00 \
  --db runs.sqlite --assume-timezone +07:00
```

```bash
python ronce.py review-claims --db runs.sqlite --run-id <RUN_ID> \
  --editor "Nama Editor" --claims claims.json --reviewed
python ronce.py render-draft --db runs.sqlite --run-id <RUN_ID> \
  --edition-id edisi-pagi --platform threads --indexes 0 --out posts.json
python ronce.py approve-edition --db runs.sqlite --run-id <RUN_ID> \
  --edition-id edisi-pagi --platform threads --editor "Nama Editor" --posts posts.json
python ronce.py preview-edition --db runs.sqlite --run-id <RUN_ID> \
  --edition-id edisi-pagi --platform threads
```

Private editor workbench (same engine, local browser UI; see the section below):

```bash
python scripts/build_workbench_demo.py .internal/workbench-demo   # synthetic demo store
export RONCE_WORKBENCH_OPERATOR="Nama Operator"
export RONCE_WORKBENCH_SECRET_HASH="$(python workbench.py --print-hash 'rahasia-yang-dipilih')"
export RONCE_WORKBENCH_DB=".internal/workbench-demo/demo.sqlite"
export RONCE_WORKBENCH_EXPORT_DIR=".internal/workbench-demo/export"
python workbench.py --port 8787
```

## CLI reference

The drift test in the suite parses this table and compares it with the parser, so the two cannot
diverge silently.

| Command | Required | Optional |
|---|---|---|
| `fetch` | `--start`, `--end`, `--out` | — |
| `fetch-companion` | `--symbol`, `--start`, `--end`, `--out` | — |
| `fetch-companion-independent` | `--symbol`, `--start`, `--end`, `--out-dir` | — |
| `schedule-once` | `pages`, `--at`, `--db`, `--interpretation` | `--since`, `--processed-at`, `--window-start`, `--window-end`, `--lookback-hours` |
| `review-claims` | `--db`, `--run-id`, `--editor`, `--claims` | `--reviewed` |
| `render-draft` | `--db`, `--run-id`, `--edition-id`, `--platform`, `--indexes` | `--out` |
| `approve-edition` | `--db`, `--run-id`, `--edition-id`, `--platform`, `--editor` | `--posts` or `--indexes` |
| `preview-edition` | `--db`, `--run-id`, `--edition-id`, `--platform` | `--posts` |
| `export-edition` | `--db`, `--run-id`, `--edition-id`, `--platform`, `--out-dir` | — |
| `replay` | `pages`, `--cutoff`, `--since`, `--db` | `--interpretation`, `--assume-timezone` |

## Sample drafts

`draft/generate_drafts.py` and `draft/generate_drafts_v2.py` are **samples**, not a production
path. Both require `--sample`, write to `draft/samples/` by default, label output
`"publishable": false` with `"review": null`, carry canonical SHA256 identities, and raise instead
of storing a platform rejection. `ronce.assert_publishable` refuses them, so no sample artifact
can enter an edition, the web export, or a social path.

## Public tree policy

`.gitignore` is an explicit allowlist (`*` plus `!` entries) with credential guards, and
`scripts/check_public_tree.py` fails when the tracked tree contains anything that is neither
allowlisted nor a documented exception. Five legacy `draft/*` artifacts remain tracked as
documented exceptions pending an owner decision; nothing else may enter the public tree.

## Web (`web/`)

A static Next.js reader that consumes the export contract and never drafts, edits or publishes.
`web/scripts/prepare-data.mjs` refuses to build when the export is not an approved edition, when
the schema version is not 1, or when any file carries `body`/credential-shaped keys.

```bash
cd web
npm ci                                        # node_modules is not part of the public tree
RONCE_EXPORT_DIR=../path/to/export npm run build   # → web/out (static)
npm run typecheck                             # tsc --noEmit (there is no ESLint config yet)
node ../scripts/browser-smoke.mjs             # real Chrome: console, focus, 390px, screenshots
```

Every page carries a provenance notice: the editorial window, when the export was built, how many
articles/stories/claims it contains, and an explicit warning when the run used the internal timezone
assumption instead of a provider confirmation. A new approved export updates the site by replacing
the export directory and re-running the build; pages are static, so nothing is served from a live
database.

Screens included: Orbit (edition cover), Warta (story list with filters), story detail with claims
and evidence, Emiten index and per-symbol pages, edition receipt with post hashes, local search,
archive policy, and per-device “Disimpan” (localStorage). Not included in this release: Kalender,
Perbandingan, aliran dana asing panels, and social orchestration — they need companion data and a
transport that do not exist yet. The editor workbench is a separate private Python runtime
(`workbench.py`), not part of this static reader.

## Editor workbench (`workbench.py`)

A private local runtime, explicitly **not a deployment**: it binds to `127.0.0.1` only, serves one
configured operator, and has no external-release action (`LIVE_PUBLISHING` stays false). It reuses
the `ronce.py` engine gates rather than duplicating them, and the public static reader stays
read-only and credential-free.

Configuration (environment; values are never committed or echoed):

```bash
export RONCE_WORKBENCH_OPERATOR="Nama Operator"
export RONCE_WORKBENCH_SECRET_HASH="$(python workbench.py --print-hash 'rahasia-yang-dipilih')"
export RONCE_WORKBENCH_DB="/path/privat/runs.sqlite"
export RONCE_WORKBENCH_EXPORT_DIR="/path/privat/export"
python workbench.py --port 8787
```

The hash format is `pbkdf2_sha256$<iterasi>$<salt_hex>$<hash_hex>` (PBKDF2-HMAC-SHA256, ≥100 000
iterations, ≥16-byte salt); an unset, malformed or unsalted digest makes startup fail closed. The
server refuses a missing configuration instead of starting half-open.

Boundary: sessions are a random 32-byte token in an `HttpOnly; SameSite=Strict` cookie with an
explicit expiry; logout and expiry invalidate immediately. Mutations are POST-only, require a
session-bound CSRF header and a loopback Host with a same-origin Origin; reads never mutate. The
request body cannot establish identity — the reviewer is always the configured principal. Every
decision carries `expected_revision_id`, checked **inside** the engine's write transaction, so a
stale tab is refused with a 409 conflict instead of silently overwriting. Audit rows
(principal, action, target, expected/actual revision, outcome, time) are persisted in
`workbench_audit`; error and log output is redacted of secret material.

Workflow API: `GET /api/session`, `POST /api/login`, `GET /api/runs`, `GET /api/candidates?run=`,
`GET /api/candidate/<story_key>`, `GET /api/audit`, `POST /api/origin-review`, `POST /api/decision`
(hold/review/approve/correct/withdraw), `POST /api/export`, `GET /api/export?edition_id=&platform=`,
`POST /api/logout`. Export writes only an approved edition, atomically, into the private export
directory; nothing here is served to the public website.

Tested limits: numeric validation is token/scale matching, not semantic understanding; an ambiguous
source number holds the candidate (abstain) instead of being guessed; origin decisions are editor
assertions, not verification of publisher identity. The workbench is covered by
`test_workbench.py` over real local HTTP requests and temporary databases (see the suite below);
it is not an independent security audit.

## Offline outbox (`outbox.py`)

A durable local queue of exact approved posts, with no network transport and no credentials. Slots
advance only when the caller reports a classified transport result or a readback:

- `outbox_plan` materializes one row per approved post, pinned to the approval's text/edition
  hashes and the explicit account; re-planning is idempotent, and a differing text/account/edition
  for an existing slot is refused. It requires a currently valid approval (a newer story revision
  makes planning fail closed).
- `outbox_record` records one transport result (`created` needs an external id). While a slot is
  `ambiguous` or `created`, a resubmit is refused — the slot must be resolved by readback first.
- `outbox_readback` verifies the post against the expected account and text. Absence is only
  accepted with an explicit operator confirmation (`confirm_absent=True`), never inferred; a
  mismatch becomes a terminal `mismatch` for manual review.
- `outbox_status` reports every slot's state and next safe action (`submit`, `readback_first`,
  `retry_after_fix`, `wait_then_retry`, `already_done`, `manual_review`).

States and transitions are listed in the module docstring; `test_outbox.py` covers the durable
slots, the no-blind-retry rules, idempotent repeats and the fail-closed plan against a revised
story, using only synthetic temporary stores.

The smoke harness drives real Chrome over CDP (no extra dependencies), checks every page for missing
content and console errors, verifies the skip link, tab order, focus outline, 390-px layout, local
search, and writes screenshots to `.internal/phase3/browser/` by default.

## Time and numbers

- Source timestamps are naive publication times in `+07:00`; replay requires an interpretation
  sidecar (or the explicit demo assumption mode) and refuses to guess.
- A live edition keeps four moments apart: the editorial slot, the news window start and end, and
  the moment the snapshot completed (`--processed-at`). A fetch that finishes after the slot no
  longer hides its own pages, and articles published after the window end stay out.
- `editorial_window` uses a 72-hour lookback on Mondays and 24 hours otherwise; holidays have no
  authoritative calendar here, so pass `--window-start` explicitly.
- Strict claims carry `value`, `unit`, `scale`, `metric`, `period` and must reproduce a fact found
  in every quoted source with the same currency, kind and scale. Opinion text additionally needs
  `claim_type: analyst_opinion` and a non-empty `attribution`.

## Environment

- Python 3.14 (the suite runs on the standard library only).
- Node.js + `twitter-text` 3.1.0 for X weighted-length rules (`npm ci --ignore-scripts`).
- `SECTORS_API_KEY` in the process environment for any live fetch; the key is never written to
  archives, logs or output.

## Explicit non-claims

- The ranking is a transparent rule score, not a return model; signals enter only when supplied
  explicitly.
- Platform limits are `documented_rules_applied`, not `platform_verified`.
- There is no unattended scheduler and no background daemon; `schedule-once` is an explicit call.
- Live fetch and the refusal matrix of the write path are tested offline only until the first
  supervised live run.
- Nothing here is investment advice or a recommendation.
