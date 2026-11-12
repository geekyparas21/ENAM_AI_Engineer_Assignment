FINN: covering note

WHAT I BUILT

FINN is a mobile-first agent that filters an investor's day. The Brief ranks every filing across a 20-stock NSE portfolio, shows the few that matter as cards, and collapses the rest: in the last seven days of data, 46 filings became 9 cards and one "routine filings hidden" row. Results cards give Revenue, EBITDA, PBT and PAT with QoQ and YoY from the filing. Alerts fire on volume and price thresholds the user sets.

FINN also researches any NSE ticker from its last five concall transcripts and latest annual report. Its centrepiece is the Promise Tracker: each management target, followed across calls, with a verdict against delivered numbers. For KPIT it finds "we will be in a position to maintain 21% EBITDA" against a delivered 18.9%. For Dixon it finds a revenue target cut one call later.

KEY DECISIONS AND TRADE-OFFS

- Rules first, model second. Regex places 87% of filings for free; a cheap model handles the rest. On a 70-filing hand-labelled set, accuracy is 81.4%.
- Code owns every number. The model reads line items and quotes; code computes, reconciles with screener.in, verifies each quote on its page, and re-checks verdicts. The model can only point at a delivered figure by key.
- Keyword retrieval (BM25), not embeddings: no quota, and a page is the unit of citation.
- The data snapshot ships with the frontend, so the demo has no cold start and survives an outage.
- It keeps running without me, and says so when it does not. Ingestion runs twice a day on a schedule and commits the snapshot, which redeploys the site. A run that cannot reach the exchange keeps the previous data rather than publishing an empty one, and never advances the "last updated" clock; /health reports the last successful ingest, its age, and the last error. When a window has no filings the Brief widens to the nearest one that does and says why, so the app is still useful days after the last run.
- Total model cost for everything: $0.79 at list price, nothing actually spent.

WHAT I DELIBERATELY LEFT OUT

Accounts, OCR for scanned filings, news, Telegram and web push, voice, and web-search enrichment for executive bios. Segment and constant-currency targets are shown but marked "Not verifiable".

WHERE I WOULD TAKE IT NEXT

Score segment-level promises from the segment tables in results filings; read the filing PDF during classification for subjects that say nothing; and let the tracker follow a company continuously, alerting when a new call moves a target.

The one piece of infrastructure I would not leave as it is: announcements have a single source. NSE works, and taking its whole-market feed in one request rather than twenty per-symbol calls makes a block far less likely, but BSE is not an alternative — its API refuses datacenter and residential requests alike. A second source, or a cached proxy, is what I would add before trusting this unattended for a long stretch.

LINKS

Live app: https://enam-ai-engineer-assignment.vercel.app/
Repository: https://github.com/geekyparas21/ENAM_AI_Engineer_Assignment
AI build history: docs/AI_HISTORY.md in the repository
Demo video: to be added
