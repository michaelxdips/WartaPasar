# WartaPasar / Ronce

**Pipeline editorial offline untuk market data IDX dari Sectors API v2**

Ronce mengarsipkan berita pasar saham secara atomik, memvalidasi keutuhan pagination, mengklaster kandidat berdasarkan tema+aksi+ticker+tanggal, dan menghasilkan draf konten editor tanpa pernah melakukan publikasi langsung. Sistem ini **100% offline** kecuali fetch read-only ke Sectors API, dengan `LIVE_PUBLISHING=False` sampai kredensial akun Threads/X tersedia dan approval eksplisit diberikan.

---

## 🎯 Fitur Utama

- **Fetch Atomik**: Arsip lengkap 57+ artikel per hari dengan validasi pagination (offset, total_count, has_next)
- **Replay Editoril**: Dedup URL, klastering tematik, pencocokan angka dua sumber independen
- **Editorial Scoring**: Bab 8.2 rules dengan scoring murni per kandidat review/abstain
- **Platform Adapters**: Kontrak offline X (Twitter) dan Threads — builder request, verification readback
- **Draft Generation**: 3-post Threads ready (GOCAP IDX, BAYAN stake transfer, KLBF earnings recovery)
- **Unicode Validator**: x_length.mjs menggunakan twitter-text@3.1.0 untuk weighted character counting

---

## 📦 Status Implementasi (2026-09-29)

### ✅ Verified Complete
- **Test Suite**: 128/128 unit tests PASS (previously fixed Unicode timeout issue)
- **Archive Integrity**: idx-2026-09-24_27.json SHA256=`7042da2e...` (read-only, immutable)
- **Live Fetch**: 57 articles successfully retrieved from 2 pages (2026-09-28)
- **Draft Content**: 3 Threads posts ready in `draft/posts-draft-v2.json`

### 🔒 Locked Features
- **LIVE_PUBLISHING=False**: Transport layer disabled until OAuth credentials provided
- **Real Account Setup**: Waiting owner's Threads/X developer account approval
- **Sectors Timestamp Rules**: Replay held pending written confirmation of timezone semantics

---

## 🛠️ Install & Setup

### Prerequisites
```bash
Python 3.10+
Node.js 18+ (for twitter-text validation)
SQLite (bundled with Python)
```

### Environment Variables
```powershell
# Set SECTORS_API_KEY safely in process environment
$env:SECTORS_API_KEY = "your-token-here"  # Never commit this!
```

Or for bash/Git Bash:
```bash
export SECTORS_API_KEY="your-token-here"
```

### Node Dependencies
```bash
cd C:\Users\Michael\Documents\Project\WartaPasar
npm ci --ignore-scripts
```

---

## 🚀 Quick Start

### 1. Fetch Live News
```bash
python ronce.py fetch --start 2026-09-24 --end 2026-09-25 --out news-2026-09-24.json
```

Output: Archive containing `request`, `response`, and `fetched_at` UTC timestamp

### 2. Run Editorial Replay
```bash
python ronce.py replay news-2026-09-24.json \
  --since 2026-09-24T06:00:00+07:00 \
  --cutoff 2026-09-25T06:00:00+07:00 \
  --db ronce.db
```

Output: SQLite database with candidate clusters and review decisions

### 3. Generate Drafts
```bash
python ronce.py review_claims --edition-id <id>
python ronce.py render_draft --platform threads
```

### 4. Run Tests
```bash
python -m unittest discover -v
# Expected: Ran 128 tests in 3.854s OK
```

---

## 📋 CLI Reference

### Core Commands

| Command | Description | Required Args | Optional Args |
|---------|-------------|---------------|---------------|
| `fetch` | Download live articles from Sectors API | `--start`, `--end`, `--out` | None |
| `replay` | Process archive through editorial pipeline | `--archive`, `--since`, `--cutoff`, `--db` | `--interpretation` |
| `review_claims` | Group candidates into themes+actions | `--archive`, `--edition-id` | None |
| `render_draft` | Build platform-specific post content | `--edition-id`, `--platform` | `--output` |
| `approve_edition` | Sign off draft with hash binding | `--edition-id`, `--signature` | `--reason` |
| `preview_edition` | Validate quotes against archive | `--edition-id` | None |
| `schedule-once` | Execute draft at specific time | `--at`, `--edition-id`, `--db` | `--since`, `--cutoff` |
| `fetch-companion` | Get companion endpoints (top-changes, foreign-flow) | `--symbol`, `--start`, `--end` | `--out` |

### Companion Endpoints
```bash
# Top changes ticker
python ronce.py fetch-companion top-changes --symbol BBCA --start 2026-09-24 --end 2026-09-25

# Foreign flow one ticker
python ronce.py fetch-companion foreign-flow --ticker JKT48.JK --start 2026-09-24 --end 2026-09-25

# Quarterly results one ticker
python ronce.py fetch-companion quarterly --ticker UNVR.JK --start 2026-09-24 --end 2026-09-25
```

---

## 🏗️ Architecture Overview

### File Structure
```
WartaPasar/
├── ronce.py              # Main CLI (core logic only)
├── adapters.py           # Offline platform contracts (X/Threads builders)
├── test_ronce.py         # 86 unit tests for editorial logic
├── test_adapters.py      # 42 unit tests for adapter contracts
├── x_length.mjs          # Twitter length validator (utf-8 byte counting)
├── package.json          # twitter-text@3.1.0 dependency
├── README.md             # This file
├── MEGA_PROMPT_FINALIZATION.md  # Internal handoff (gitignored, not pushed)
├── data/                 # Read-only archives (gitignored, never committed)
│   └── idx-2026-09-24_27.json
├── draft/                # Workspace drafts (gitignored, generated files)
│   ├── posts-draft-v2.json
│   └── generate_drafts_v2.py
└── node_modules/         # Dependencies (gitignored)
```

### Git Allowlist (Public Files Only)
Only these 9 files may be committed/pushed to public repository:
1. `.gitignore`
2. `README.md`
3. `ronce.py`
4. `adapters.py`
5. `test_ronce.py`
6. `test_adapters.py`
7. `package.json`
8. `package-lock.json`
9. `x_length.mjs`

All other files are workspace artifacts or internal documentation.

---

## 🧪 Test Coverage

### Total: 128 Unit Tests

#### Editorial Logic (`test_ronce.py`)
- **ReplayTests** (28 tests): Pagination validation, dedup URL, timezone handling, editorial window filtering
- **ScoringTests** (12 tests): Bab 8.2 rule application, input validation only
- **TopicVocabularyTests** (15 tests): Dwibahasa ID/EN, vocabulary families, precision traps

#### Adapter Contracts (`test_adapters.py`)
- **BuildTests** (14 tests): Request builder for both platforms, header/auth simulation
- **ClassifyResponseTests** (10 tests): Response state classification
- **VerifyReadbackTests** (12 tests): Account/text/link matching verification

### Running Tests
```bash
# Full suite
python -m unittest discover -v

# Specific test group
python -m unittest test_ronce.ReplayTests -v

# With coverage (requires pytest-cov)
pytest --cov=ronce --cov-report=html
```

---

## 🔐 Security & Credentials

### NEVER Commit
❌ `SECTORS_API_KEY`
❌ `THREADS_CLIENT_ID`
❌ `THREADS_CLIENT_SECRET`
❌ `X_API_KEY`
❌ `X_API_SECRET`
❌ Any OAuth tokens

### Safe Practices
✅ Use environment variables only: `$env:SECTORS_API_KEY`
✅ Create `.env.example` template (gitignored)
✅ Document credential setup steps in separate private guide
✅ Rotate tokens monthly, revoke old ones immediately

---

## 🚧 Known Limitations

### Current Blocks
1. **Timestamp Semantics**: Replay held pending written confirmation from Sectors about:
   - `source_timezone` (which zone?)
   - `timestamp_meaning` (publication vs indexing?)
   - `filter_timezone` (apply filter in which zone?)
   - `start_inclusive` / `end_inclusive` (boundary conditions?)

2. **No Real Accounts**: `LIVE_PUBLISHING=False` until:
   - Owner's Threads account (@username) registered
   - Meta Developer app approved
   - OAuth2 credentials secured

3. **No Cross-Platform Ranking**: Single-platform scoring per topic; no priority ranking across categories yet

4. **Scheduler Daemon**: Only `schedule-once` implemented; no cron daemon or continuous background process

5. **Mock Post Simulator**: Bug class learned from missing read-back requirement; needs implementation

---

## 📅 Future Roadmap

### Phase A2: Pilot Threads Read-Back (Next Priority)
- Mock transport layer for testing builder output
- Full verification flow: build → mock submit → mock readback → verify
- 25+ test cases covering success/fail scenarios
- Documentation for OAuth integration pattern

**Timeline**: 1-2 sessions
**Dependencies**: None (pure offline Python)

### Phase B1: Connect Real Threads Account
- OAuth2 client credentials integration
- Draft submission workflow: review → approve → publish → verify
- Rate limiting handler with retry logic via `plan_next_action()`
- Monitoring logs (success/fail/error metrics)

**Timeline**: 2-3 sessions (after A2 complete)
**Dependencies**: Meta Developer account approval

### Phase C5: Extend to X (Twitter) Platform
- OAuth1.0a User Context implementation
- Thread sequencing (reply chaining via `in_reply_to_tweet_id`)
- Weighted character limit enforcement (already fixed ✅)
- Cross-platform consistency checks

**Timeline**: 2 sessions parallel to B1
**Dependencies**: X developer account approval

### Phase D: Editorial Workflow Dashboard
- Interactive CLI interface for editorial decisions
- Grouped candidate presentation by theme + action + ticker
- Editor commands: y=approve, n=abstain, r=revise_request
- Hash-bound approval + revision tracking

**Timeline**: 2-3 sessions
**Dependencies**: UI preference decision (CLI vs web simple)

---

## 🤝 Contribution Guidelines

### Before Committing
1. ✅ Verify working tree clean (`git status` shows nothing to commit)
2. ✅ No AI/tool references in diff (`grep -i "mcode\|AI" --include=\*.py .`)
3. ✅ Pass pre-commit hooks (`git diff --check` returns 0 errors)
4. ✅ All tests pass (`python -m unittest discover -v` exit code 0)
5. ✅ Commit message without tool/AI names

### Commit Identity (Mandatory)
```bash
git -c user.name="Stephen Michael S" \
    -c user.email="142143611+michaelxdips@users.noreply.github.com" \
    commit -m "Feature description without AI references"
```

### Push Protocol
⚠️ **NO auto-push** — explicit owner approval required for every `git push`
⚠️ **NO sensitive files** — only allowlist 9 files allowed
⚠️ **NO history rewrite** — never use `git filter-branch` without backup

---

## 📞 Support & Handoff

### Current Contact
**Owner**: Stephen Michael S
**GitHub**: michaelxdips/WartaPasar
**Last Updated**: 2026-09-29 12:30 WIB Western Indonesia Time

### Documentation Files
- **MEGA_PROMPT_FINALIZATION.md**: Internal handoff document (gitignored, not pushed)
- **ARCHITECTURE.md**: Planned future addition for system design docs
- **CONTRIBUTING.md**: Planned future addition for external contributors

---

## ⚖️ License & Terms

This project is private/internal-use only. No license granted for external redistribution. All source code belongs to Stephen Michael S. Third-party dependencies retain their respective licenses:

- `twitter-text@3.1.0`: BSD 3-Clause License
- `unittest`: Python Software Foundation License

---

## 🔄 Version History

### v2.0 (2026-09-29)
- ✅ Fix Windows subprocess Unicode encoding for x_length.mjs
- ✅ Add MEGA_PROMPT_FINALIZATION.md and draft content from live fetch
- ✅ Add offline Threads reply builder and scheduler robustness tests
- ✅ Clean up git history (remove internal docs from public repo)

### v1.0 (2026-09-28)
- Initial MVP: fetch/archive/replay/editorial pipeline
- 128 unit tests baseline
- Offline adapter contracts for X/Threads

---

**Built with care for accurate market data curation.** 📊✨
