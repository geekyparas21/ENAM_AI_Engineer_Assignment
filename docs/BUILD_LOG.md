# FINN build log

A running record of what was built each session, the decisions taken and why, and what
broke. Newest session last.

## Session 1 — 10–11 Nov 2026 — data plumbing, the Brief, results cards

**Built**

- Ingest for the 20-stock portfolio: EOD price and volume from yfinance, 30 days of NSE
  corporate announcements (271 filings), stored in SQLite and exported as a snapshot.
- Two-stage classifier. Stage 1 is ordered regex rules over the exchange's own category
  and the subject line; it places 236 of 271 filings (87%). The 35 it cannot place are
  held for the cheap model rather than guessed.
- Ranking in code: category base weight × paperwork demotion × role modifier × "did the
  stock react" modifier. Every score carries its reasons, shown on the card.
- Results card for all 17 Q2 FY27 results filings: Revenue, EBITDA, PBT, PAT with QoQ
  and YoY, margins in percentage points, and a one-line takeaway composed in code.
- Frontend (Next.js, mobile-first): Brief, Alerts, Research (portfolio list for now),
  Settings. Seen / Star / Mute stored per device and fed back into ranking.
- One router for all model calls (`backend/finn/llm.py`): tier per task, response cache,
  retry with backoff, token and cost log. 49 unit tests, none needing a network or key.

**Decisions**

- **NSE is the announcements source, not BSE.** BSE's announcements API returned 403 to
  both a plain request and a browser-like session, so we did not push further. NSE's API
  works with the documented homepage-cookie flow. This also removed the need for an
  NSE-symbol-to-BSE-code map.
- **The Brief's window ends at the last successful fetch, not the wall clock.** If
  ingestion falls behind, "last 24h" still means the latest 24h of data we hold, and the
  header shows the exact range. An honest stale view beats an empty one.
- **Results cards have two legs.** The filing PDF is primary (a model reads line items
  off the P&L page; code does all arithmetic and checks PBT − tax = PAT). screener.in's
  standardised quarterly table is the cross-check, and the fallback when a filing cannot
  be read. A fallback card says so and why. Reason: 2 of 17 filings were unreadable
  (see below), and a card with a stated source beats a missing card.
- **Alert thresholds are evaluated on the device.** Ratios and baselines are computed in
  Python at ingest; the comparison against the user's sliders happens in the browser, so
  moving a slider is instant and works while the backend is asleep.
- **The top-of-Brief summary is composed in code, not by a model.** It is built from the
  ranked cards and price data, so it costs nothing and cannot state anything the cards
  do not.
- **Same-day filings for one event are clustered.** A company often files the results,
  the deck and the board outcome separately; the Brief shows one card with the rest
  tucked behind it.
- **Unpriced models report "not priced", not a guessed cost.** Model prices are
  configuration, filled from the provider's pricing page.

**What broke, and the fix**

- *BSE API 403.* Switched to NSE (above).
- *Rounding before computing.* The first results maths rounded to ₹ crore and then
  computed growth, which moved KPIT's PAT QoQ from 3.6% to 3.7%. A unit test written from
  the filing's own numbers caught it; growth is now computed at full precision and
  rounded only for display.
- *Results PDFs are messier than expected.* HDFC Bank's filing is truncated on NSE's own
  server (cut off mid-object at 960 KB); Deepak Nitrite's is an image-only scan; and OCR
  noise ("fmance costs") made an exact-phrase page finder miss the consolidated statement
  for Bharti Airtel and Sun Pharma. The page finder now scores pages by how many P&L line
  items they contain and picks the consolidated statement in all 13 readable filings; the
  two unreadable ones use the screener fallback.
- *Monospace everywhere looked like a terminal.* Mono is now used for tickers only;
  numbers use the sans face with tabular figures.
- *Default 24h window was empty* (10 Nov had no session or filings). The empty state now
  offers the nearest window that has something material.

**Checked against source**

- KPIT, Dixon and Titan card figures were compared by hand with the P&L page of each
  results PDF (revenue, PBT, PAT, year-ago values). All matched.

**Not done yet**

- No model key was available this session, so stage-2 classification, filing-parsed
  results cards, one-line summaries and management-change cards are written and tested
  against a fake provider but have not run against a real model.
- Not deployed. Hand-labelled classifier eval set not started.

## Session 1, continued — 11 Nov 2026 — first run against a real model

**Built**

- Ran the model steps on the real filings with a Gemini free-tier key
  (`gemini-3.5-flash-lite` for every cheap-tier task): 35 ambiguous filings classified,
  results line items read from the filing PDFs, people cards for 17 of 18 management
  changes, and 71 one-line summaries. About 190k input tokens in total.

**Decisions**

- **A results card must reconcile with screener.in in all three quarters.** Comparing
  filing-parsed cards with screener showed revenue, PBT and PAT matching exactly for 11
  of 15 companies, but the model had read the wrong revenue line for ITC and Infosys and
  wrong prior-period figures for CDSL. If revenue, PBT or PAT disagree in any of the
  three quarters, the card now falls back to screener's table and says why. A confident
  wrong headline is worse than a labelled fallback. EBITDA differences only raise a
  warning, because the two sources can treat other income differently.
- **One failed filing no longer stops the run.** A model error on a single filing is
  counted and skipped; it is retried on the next run.

**What broke, and the fix**

- *Empty `FINN_DATA_DIR=` in a freshly copied `.env` pointed the pipeline at the current
  folder*, which created an empty database and wrote an empty snapshot over the
  frontend's copy. The real database was untouched. An empty value now means "use the
  default".
- *The default model id was retired.* `gemini-2.5-flash-lite` is closed to new keys; the
  cheap tier is now set in `.env`. Model ids are configuration for exactly this reason.
- *A temporary "high demand" error from the provider aborted every later step.* Fixed as
  above.

**Known gaps from this run**

- The model labelled one Reliance filing about Jio Platforms' listing as `results`; it
  should be `M&A`. The hand-labelled eval set will measure how often this happens.
- Tiny penalties (a ₹2.6 lakh notice to Bharti Airtel) still rank as material. Size
  relative to market cap is not yet part of the score.
- Model prices are not configured, so the cost line reads "not priced".

**Deployed**

- Frontend is live on Vercel at https://enam-ai-engineer-assignment.vercel.app/, built from
  `frontend/` and redeployed on every push to `main`. It serves the committed snapshot, so
  there is no backend to wake up. Checked at 375px on the live URL: all four screens, both
  themes, no horizontal overflow, no console errors.
- No backend is deployed yet. It becomes necessary when Research needs live document
  processing.

## Session 2 — 11 Nov 2026 — Research engine, evaluation, deployment plumbing

**Built**

- Research for any NSE ticker: the last five concall transcripts and the latest annual
  report are read once and cached per page; six companies are built and shipped with the
  app (KPITTECH, DIXON, PERSISTENT, ASTRAL, TITAN, and KAYNES from outside the portfolio).
- Promise Tracker: a cheap model lists guidance with a verbatim quote and page; code checks
  the quote is really on that page; a stronger model groups statements into threads and
  gives a verdict, referring to delivered figures only by key; code fills in the numbers
  and re-checks every verdict it can compute.
- Financial tabs (snapshot, trajectory, cash quality, balance sheet) computed entirely in
  code from screener.in's standardised tables. Business snapshot, bull and bear, and Ask
  FINN are written only from retrieved pages and computed figures; anything uncited is
  removed before it is shown.
- Research screen with live progress for a first-time ticker (Titan built in 52 seconds
  through the UI), a hand-labelled classifier eval (81.4% for rules + model), a Render
  blueprint, a GitHub Actions ingestion workflow, and a service worker for offline use.

**Decisions**

- **BM25, not embeddings.** The prompt suggested embeddings. Questions about filings are
  keyword-heavy and a page is the unit of citation, so lexical retrieval over pages fits,
  and it needs no model download (too heavy for a free-tier instance) and no API quota.
  Its weakness is synonyms: "customer concentration" missed a page about "top two
  accounts". A cheap query-expansion call plus rank fusion fixed that case.
- **The model points at numbers; it never writes them.** In verdict evidence the model
  writes `{FY26.ebitda_margin}` and code substitutes 18.9%. An unknown key is never shown
  as a number.
- **"Ahead" or "behind" needs a reported figure for the target's own period.** The model
  called targets "on track" because management repeated them. That label is now removed
  unless a figure for that period supports it, and a FY29 target is no longer compared
  with FY27 numbers.
- **The strong tier falls back to the cheap model.** Gemini's free tier allows 20 requests
  a day on the stronger model. An exhausted daily quota now skips retries and falls back
  immediately; the result records which model answered and is not cached.
- **Tiny penalties are routine.** A legal filing whose stated amount is under ₹1 crore is
  demoted, so a ₹2.6 lakh notice to Bharti Airtel no longer sits beside an insolvency order.
- **The classifier was not tuned on its eval set.** Two rule fixes are obvious from the
  misses; they are listed in the README instead of applied, so the reported number is honest.

**What broke, and the fix**

- *Analysts quoted as management.* "You had said Q2 would be flattish" was extracted as
  guidance. Second-person address and questions are now rejected in code.
- *Citations one page off.* Quotes were matched against a page plus the next one, so a
  quote on page 5 could be cited as page 4. A test caught it; a single-page match now
  wins, and re-verifying the built research corrected 11 of 65 page numbers.
- *Regex word boundaries written as backspace characters* by a shell heredoc, silently
  disabling a filter. Found by a failing assertion; source edits now avoid that path.
- *Stale stylesheet in the Next.js build cache* left chart marks black. Fixed by a clean
  build; chart colours were validated for both themes with a palette checker.
- *Quota exhaustion left research half-built.* Three of four companies were missing a
  section. Fixed by the fallback above and a rebuild.

**Checked**

- 77 unit tests, all offline. Research tabs, Ask FINN and a first-time build were driven
  through the real UI at 375px in both themes with no layout overflow.
