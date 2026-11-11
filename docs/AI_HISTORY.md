# AI build history

Every coding-agent session used to build FINN. The exported conversation for each session
is linked in the last column.

| # | Date | Tool | What it covered | Export |
|---|------|------|-----------------|--------|
| 1 | 10–11 Nov 2026 | Claude Code (VS Code extension) | Read the brief and build prompt; data plumbing (yfinance, NSE announcements, screener.in); rule classifier; ranking and alerts; results cards with filing/screener legs; Next.js app (Brief, Alerts, Research list, Settings); model router and tests | [Session 1](session-01.md) |
| 2 | 11 Nov 2026 | Claude Code (VS Code extension) | Same conversation, continued (this export includes session 1's text): git identity and GitHub repo setup; first run against a real model (Gemini) for classification, filing-parsed results, people cards and summaries; stricter reconciliation of results against screener.in; Vercel deployment and live checks | [Session 2](session-02.md) |
| 3 | 11 Nov 2026 | Claude Code (VS Code extension) | Research engine (Promise Tracker, cited snapshot, bull/bear, Ask FINN), Research screen, quota-aware model fallback, classifier eval, size-aware ranking, Render blueprint, ingestion workflow, service worker, README and write-up | [Session 3](session-03.md) |


See [BUILD_LOG.md](BUILD_LOG.md) for the decisions and dead ends in each session.
