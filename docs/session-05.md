
> The Brief page shows "Data as of 10 Nov, 23:50 IST · saved snapshot" and the
  24h window is empty on 13 Nov. Data is not auto-updating. Fix in this order:

  1. Diagnose: check whether the GitHub Actions ingestion workflow exists, is
  enabled, and when it last ran. Open the latest run logs and tell me exactly
  where it fails (fetch blocked by NSE/BSE, missing secrets, write step, or
  deploy step). Also check how the deployed app reads data: confirm new data
  actually reaches the live site (DB write, committed snapshot, or a Vercel
  redeploy trigger).
  2. Fix the pipeline so the live site updates at least twice a day (e.g. 18:30
  and 23:30 IST; cron runs in UTC). If NSE blocks the runner, use the BSE API
  as the primary source. Add a manual "Run workflow" trigger
  (workflow_dispatch) so I can refresh before the demo. After fixing, trigger a
  run and show me the live site with today's timestamp.
  3. Make the empty state robust, because evaluators may open the app days
  later:
     - If the chosen window has no items, don't show a blank page. Say "Nothing
  new in the last 24h. Latest filings are from <date>" and show those latest
  material items below, or switch to 3d automatically with a visible note.
     - The "Data as of" label must show the real latest ingestion time. Show
  "saved snapshot" only when live fetch truly failed, and include a one-line
  reason.
  4. Add a small health check: a /health endpoint showing last successful
  ingest time, item count, and last error. Note it in the README.

  Record the cause and the fix in docs/BUILD_LOG.md.
  the website link is https://enam-ai-engineer-assignment.vercel.app/

● Let me read the project structure and relevant files to diagnose the issues.

  Searched for 3 patterns, read 6 files, listed 1 directory, ran 1 shell command (ctrl+o to expand)

● Now let me look at the frontend to understand how data is read and displayed.

  Searched for 5 patterns, read 6 files, ran 1 shell command (ctrl+o to expand)

● Let me check the prices source and repo variable setup.

  Read 1 file, ran 1 shell command (ctrl+o to expand)

● Good. Now I have a clear picture. Let me check the Next.js app structure for
  the API route.

  Searched for 1 pattern, read 3 files, ran 1 shell command (ctrl+o to expand)

● I now have the full picture. Let me implement all the fixes.

  Root causes:
  1. FINN_INGEST_ENABLED repo variable is not set → workflow guard blocks every
     run
  2. NSE may block GitHub Actions datacenter IPs → need BSE fallback
  3. 24h window is empty because snapshot is 3 days stale (10 Nov) and 10 Nov
     had no material filings
  4. Empty state doesn't explain staleness; "saved snapshot" label is misleading

● Before writing fixes, let me verify the actual workflow run history with the
  GitHub CLI.

  Ran 3 shell commands (ctrl+o to expand)

● Key finding. Let me confirm the workflow never ran and test source
  reachability.

  Ran 2 shell commands (ctrl+o to expand)

● NSE works from here (4 recent filings); BSE returns 403 even from a
  residential IP. Let me test whether BSE works with session priming before I
  rule it out.

  Ran 1 shell command (ctrl+o to expand)

● BSE is genuinely dead (403 even primed). But the NSE all-market feed returns
  8,876 rows in a single call — that's a far more robust path than 20 per-symbol
  calls. Let me verify it covers the portfolio.

  Ran 1 shell command (ctrl+o to expand)

● Conclusive. The all-market feed has 111 portfolio filings through 12 Nov —
  including 23 the stale snapshot is missing — and uses identical field names to
  the existing parser. Now let me implement.

  First, the NSE source gets a single-call all-market path (1 request instead of
  20, far less likely to be blocked on a runner):

● Update(backend\finn\sources\nse.py)
  ⎿  Added 25 lines, removed 10 lines
       2  
       3  NSE needs a browser-like session: load the homepage once to rec
          eive cookies, then
       4  call the JSON API with the same session. BSE's API refused our 
          requests outright
       5 -(403), so NSE is the primary source; see docs/BUILD_LOG.md.    
       5 +(403, re-confirmed from a residential IP with and without homep
         +age priming), so NSE                                           
       6 +is the only source; see docs/BUILD_LOG.md.                     
       7 +                                                               
       8 +Prefer `all_announcements`: the same endpoint without a `symbol
         +` returns the whole                                            
       9 +market for the date range in ONE request, which we filter local
         +ly. Twenty per-symbol                                          
      10 +calls give NSE twenty chances to rate-limit a datacenter IP; on
         +e call gives it one.                                           
      11 +`announcements` remains as the per-symbol fallback.            
      12  """
      13  from __future__ import annotations
      14  
     ...
      40          self.session.get(HOME, timeout=30).raise_for_status()
      41          self._primed = True
      42  
      37 -    def announcements(self, symbol: str, start: date, end: date
         -) -> list[dict]:                                               
      43 +    def _fetch(self, params: dict, what: str, timeout: int) -> 
         +list[dict]:                                                    
      44          if not self._primed:
      45              self._prime()
      40 -        params = {                                             
      41 -            "index": "equities",                               
      42 -            "symbol": symbol,                                  
      43 -            "from_date": start.strftime("%d-%m-%Y"),           
      44 -            "to_date": end.strftime("%d-%m-%Y"),               
      45 -        }                                                      
      46          last_exc: Exception | None = None
      47          for attempt in range(3):
      48              try:
      49 -                resp = self.session.get(API, params=params, tim
         -eout=30)                                                       
      49 +                resp = self.session.get(API, params=params, tim
         +eout=timeout)                                                  
      50                  if resp.status_code in (401, 403):
      51                      self._prime()  # cookie expired: refresh on
          ce and retry
      52                      raise requests.HTTPError(f"NSE {resp.status
          _code}")
     ...
      56              except Exception as exc:  # noqa: BLE001 - retried,
           then surfaced
      57                  last_exc = exc
      58                  time.sleep(1.5 * (attempt + 1))
      59 -        raise RuntimeError(f"NSE announcements failed for {symb
         -ol}: {last_exc}")                                              
      59 +        raise RuntimeError(f"NSE announcements failed for {what
         +}: {last_exc}")                                                
      60  
      61 +    def all_announcements(self, start: date, end: date) -> list
         +[dict]:                                                        
      62 +        """Every equity filing in the range, in one request. Fi
         +lter to a portfolio locally."""                                
      63 +        return self._fetch(                                    
      64 +            {"index": "equities",                              
      65 +             "from_date": start.strftime("%d-%m-%Y"),          
      66 +             "to_date": end.strftime("%d-%m-%Y")},             
      67 +            "the whole market", timeout=90)                    
      68  
      69 +    def announcements(self, symbol: str, start: date, end: date
         +) -> list[dict]:                                               
      70 +        return self._fetch(                                    
      71 +            {"index": "equities", "symbol": symbol,            
      72 +             "from_date": start.strftime("%d-%m-%Y"),          
      73 +             "to_date": end.strftime("%d-%m-%Y")},             
      74 +            symbol, timeout=30)                                
      75 +                                                               
      76 +                                                               
      77  def normalise(row: dict) -> dict:
      78      ts = datetime.strptime(row["an_dt"], "%d-%b-%Y %H:%M:%S")
      79      return {

● The all-market feed normalises 8,876 rows, so one malformed row anywhere in
  the market would kill the whole fetch. Let me make that tolerant:

● Update(backend\finn\sources\nse.py)
  ⎿  Added 9 lines, removed 1 line
      52                      raise requests.HTTPError(f"NSE {resp.status
          _code}")
      53                  resp.raise_for_status()
      54                  time.sleep(self.pause)
      55 -                return [normalise(row) for row in resp.json()] 
      55 +                # The all-market feed carries thousands of rows
         + from across the exchange.                                     
      56 +                # One unparseable date there must not cost us t
         +he whole fetch.                                                
      57 +                out = []                                       
      58 +                for row in resp.json():                        
      59 +                    try:                                       
      60 +                        out.append(normalise(row))             
      61 +                    except Exception:  # noqa: BLE001,PERF203  
      62 +                        continue                               
      63 +                return out                                     
      64              except Exception as exc:  # noqa: BLE001 - retried,
           then surfaced
      65                  last_exc = exc
      66                  time.sleep(1.5 * (attempt + 1))

● Now rewrite the fetch script to use the single all-market call with per-symbol
  fallback, and record a real error/ingest log:

● Write(ingest\fetch.py)
  ⎿  Added 58 lines, removed 13 lines
       2  
       3  Run: python ingest/fetch.py [--days 30]
       4  Each source fails independently: a blocked exchange must not st
          op prices, and vice versa.
       5 +                                                               
       6 +Announcements take the whole-market NSE feed in one request and
         + filter to the portfolio                                       
       7 +locally, falling back to per-symbol calls only if that one requ
         +est fails. Twenty requests                                     
       8 +give NSE twenty chances to rate-limit a datacenter IP; one give
         +s it one.                                                      
       9  """
      10  from __future__ import annotations
      11  
     ...
      21  from finn.sources import nse, prices  # noqa: E402
      22  
      23  
      24 +def fetch_announcements(conn, client: nse.NSEClient, start: dat
         +e, end: date) -> tuple[int, list[str], str | None]:            
      25 +    """Returns (new rows stored, symbols that failed, error to 
         +record if the feed was blocked)."""                            
      26 +    try:                                                       
      27 +        market = client.all_announcements(start, end)          
      28 +        mine = [r for r in market if (r.get("symbol") or "").up
         +per() in PORTFOLIO]                                            
      29 +        new = nse.store_announcements(conn, mine)              
      30 +        print(f"all-market feed: {len(market)} filings, {len(mi
         +ne)} for the portfolio, {new} new")                            
      31 +        return new, [], None                                   
      32 +    except Exception as exc:  # noqa: BLE001                   
      33 +        print(f"all-market feed FAILED ({exc}); falling back to
         + per-symbol calls")                                            
      34 +        feed_error = f"all-market feed: {exc}"                 
      35 +                                                               
      36 +    new_total, failed = 0, []                                  
      37 +    for sym in PORTFOLIO:                                      
      38 +        try:                                                   
      39 +            n = nse.store_announcements(conn, client.announceme
         +nts(sym, start, end))                                          
      40 +            new_total += n                                     
      41 +            print(f"  {sym:<12} {n} new")                      
      42 +        except Exception as exc:  # noqa: BLE001               
      43 +            failed.append(sym)                                 
      44 +            print(f"  announcements FAIL {sym}: {exc}")        
      45 +    # Only a total per-symbol wipeout is worth recording as the
         + run's error.                                                  
      46 +    return new_total, failed, feed_error if len(failed) == len(
         +PORTFOLIO) else None                                           
      47 +                                                               
      48 +                                                               
      49  def main() -> int:
      50      ap = argparse.ArgumentParser()
      51      ap.add_argument("--days", type=int, default=30, help="annou
          ncement look-back window")
     ...
      54      end = date.today()
      55      start = end - timedelta(days=args.days)
      56      client = nse.NSEClient()
      28 -    price_fail, ann_fail = [], []                              
      57 +    price_fail: list[str] = []                                 
      58  
      59      with db.session() as conn:
      60          for sym in PORTFOLIO:
     ...
       65              except Exception as exc:  # noqa: BLE001
       66                  price_fail.append(sym)
       67                  print(f"price FAIL {sym}: {exc}")
       39 -            try:                                              
       40 -                new = nse.store_announcements(conn, client.ann
          -ouncements(sym, start, end))                                  
       41 -                print(f"{sym:<12} prices ok, {new} new announc
          -ements")                                                      
       42 -            except Exception as exc:  # noqa: BLE001          
       43 -                ann_fail.append(sym)                          
       44 -                print(f"announcements FAIL {sym}: {exc}")     
       45 -            conn.commit()                                     
       68 +        conn.commit()                                         
       69  
       70 +        new_anns, ann_fail, ann_error = fetch_announcements(co
          +nn, client, start, end)                                       
       71 +        conn.commit()                                         
       72 +                                                              
       73          now = datetime.now(timezone.utc).isoformat(timespec="s
           econds")
       48 -        if len(price_fail) < len(PORTFOLIO):                  
       74 +        prices_ok = len(price_fail) < len(PORTFOLIO)          
       75 +        anns_ok = len(ann_fail) < len(PORTFOLIO)              
       76 +        if prices_ok:                                         
       77              db.set_meta(conn, "prices_fetched_at", now)
       50 -        if len(ann_fail) < len(PORTFOLIO):                    
       78 +        if anns_ok:                                           
       79              db.set_meta(conn, "announcements_fetched_at", now)
       80 +                                                              
       81 +        # The health endpoint reads these, so a blocked source
          + is visible without the run log.                              
       82 +        db.set_meta(conn, "last_fetch_attempted_at", now)     
       83 +        errors = []                                           
       84 +        if not prices_ok:                                     
       85 +            errors.append("every price fetch failed (yfinance 
          +unreachable)")                                                
       86 +        if ann_error:                                         
       87 +            errors.append(ann_error)                          
       88 +        elif not anns_ok:                                     
       89 +            errors.append("every per-symbol announcement call 
          +failed (NSE blocked this runner)")                            
       90 +        elif price_fail:                                      
       91 +            errors.append(f"prices missing for {', '.join(pric
          +e_fail)}")                                                    
       92 +        db.set_meta(conn, "last_fetch_error", "; ".join(errors
          +) if errors else "")                                          
       93 +        if not errors:                                        
       94 +            db.set_meta(conn, "last_fetch_ok_at", now)        
       95 +                                                              
       96          total = conn.execute("SELECT COUNT(*) c FROM announcem
           ents").fetchone()["c"]
       97 +        conn.commit()                                         
       98  
       54 -    print(f"\nannouncements in db: {total}; price failures: {p
          -rice_fail or 'none'}; "                                       
       55 -          f"announcement failures: {ann_fail or 'none'}")     
       56 -    return 1 if (len(price_fail) == len(PORTFOLIO) and len(ann
          -_fail) == len(PORTFOLIO)) else 0                              
       99 +    print(f"\nannouncements in db: {total} ({new_anns} new thi
          +s run); "                                                     
      100 +          f"price failures: {price_fail or 'none'}; announceme
          +nt failures: {ann_fail or 'none'}")                           
      101 +    return 1 if (not prices_ok and not anns_ok) else 0        
      102  
      103  
      104  if __name__ == "__main__":

● Now surface those into the snapshot so the health endpoint and UI can read
  them:

  Searched for 1 pattern (ctrl+o to expand)

● Update(backend\finn\snapshot.py)
  ⎿  Added 7 lines
      107              "announcements": db.get_meta(conn, "announcements_
           fetched_at"),
      108              "last_session": max((p["date"] for p in portfolio 
           if p["date"]), default=None),
      109          },
      110 +        # Ingest health, so /health and the "data as of" line 
          +can tell a successful                                         
      111 +        # refresh apart from a blocked one without reading the
          + workflow log.                                                
      112 +        "ingest": {                                           
      113 +            "last_ok_at": db.get_meta(conn, "last_fetch_ok_at"
          +),                                                            
      114 +            "last_attempted_at": db.get_meta(conn, "last_fetch
          +_attempted_at"),                                              
      115 +            "last_error": db.get_meta(conn, "last_fetch_error"
          +) or None,                                                    
      116 +        },                                                    
      117          "material_threshold": MATERIAL_THRESHOLD,
      118          "defaults": DEFAULT_SETTINGS,
      119          "portfolio": portfolio,

● Now the workflow — removing the guard that blocked every run, and fixing the
  schedule:

● Write(.github\workflows\ingest.yml)
  ⎿  Added 23 lines, removed 5 lines
       5  # the job keeps the previous snapshot rather than publishing an
           empty one.
       6  on:
       7    schedule:
       8 -    - cron: "30 11 * * 1-5"    # 17:00 IST on trading days, aft
         -er the close                                                   
       9 -    - cron: "0 3,7,15 * * *"   # 08:30, 12:30 and 20:30 IST for
         - announcements                                                 
       8 +    # Cron is UTC. 13:00 UTC = 18:30 IST (after the close), 18:
         +00 UTC = 23:30 IST                                             
       9 +    # (catches filings made through the evening).              
      10 +    - cron: "0 13 * * 1-5"                                     
      11 +    - cron: "0 18 * * 1-5"                                     
      12    workflow_dispatch:
      13  
      14  permissions:
     ...
      20  
      21  jobs:
      22    ingest:
      21 -    # Opt-in: runs only once the repository variable FINN_INGES
         -T_ENABLED is 'true' and the                                    
      22 -    # GEMINI_API_KEY secret is set. Without the key the model-w
         -ritten cards would be lost.                                    
      23 -    if: ${{ vars.FINN_INGEST_ENABLED == 'true' }}              
      23      runs-on: ubuntu-latest
      24      timeout-minutes: 25
      25      steps:
     ...
      41            key: finn-data-${{ github.run_id }}
      42            restore-keys: finn-data-
      43  
      44 +      # Announcements come from NSE's whole-market feed in one 
         +request (filtered to the                                       
      45 +      # portfolio locally), falling back to per-symbol calls. P
         +rices come from Yahoo, which                                   
      46 +      # does not block datacenter IPs. A blocked NSE is recorde
         +d in the snapshot's                                            
      47 +      # ingest.last_error and surfaced by /health rather than f
         +ailing silently.                                               
      48        - name: Fetch prices and announcements
      49          run: python ingest/fetch.py --days 30
      50          continue-on-error: true
      51  
      52 +      # Runs with or without a model key: without one the model
         + steps are skipped and                                         
      53 +      # results cards come from the screener fallback, so the s
         +napshot still refreshes.                                       
      54        - name: Classify, enrich, rank and export
      55          env:
      56            GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
     ...
      58            FINN_STRONG_MODEL: gemini:gemini-3.5-flash
      59          run: python ingest/process.py
      60  
      61 +      - name: Report what the snapshot now holds               
      62 +        run: |                                                 
      63 +          python - <<'PY'                                      
      64 +          import json, pathlib                                 
      65 +          s = json.loads(pathlib.Path("data/snapshot.json").rea
         +d_text(encoding="utf-8"))                                      
      66 +          ing = s.get("ingest") or {}                          
      67 +          print("generated_at   :", s["generated_at"])         
      68 +          print("as_of          :", s["as_of"])                
      69 +          print("filings        :", len(s["announcements"]))   
      70 +          print("last ingest ok :", ing.get("last_ok_at"))     
      71 +          print("last error     :", ing.get("last_error") or "n
         +one")                                                          
      72 +          PY                                                   
      73 +                                                               
      74        - name: Commit the snapshot if it changed
      75          run: |
      76            git config user.name "finn-ingest"

● Let me run the fixed pipeline locally to prove it works and get fresh data.

  Ran 2 shell commands (ctrl+o to expand)

● Found a second, independent failure: every price fetch is broken with NOT NULL
  constraint failed: prices.close. Announcements worked (23 new filings). Let
  me diagnose the price regression.
  Ran 1 shell command (ctrl+o to expand)

● yfinance is fine — but one NaN-close row out of 22 poisons the whole
  executemany batch for every symbol. The code guards
  prev_close/pct_change/avg_vol_20 against NaN but never close itself. Let me
  confirm which row, then fix:

  Ran 1 shell command (ctrl+o to expand)

● Confirmed: the NaN row is 12 Nov — the latest session, which has volume but no
  settled close, so it passes the Volume > 0 filter and then violates NOT NULL.
  Fixing:

● Update(backend\finn\sources\prices.py)
  ⎿  Added 7 lines, removed 1 line
      15      hist = yf.Ticker(f"{symbol}.NS").history(period=period, int
          erval="1d", auto_adjust=False)
      16      if hist.empty:
      17          return []
      18 -    hist = hist[hist["Volume"] > 0]                            
      18 +    # Yahoo publishes the newest session's volume before its cl
         +ose has settled, giving a                                      
      19 +    # row with Volume > 0 but Close NaN. Such a row is not a se
         +ssion we can store or chart,                                   
      20 +    # and dropping it before the shift/rolling maths keeps it o
         +ut of the next day's                                           
      21 +    # prev_close and the 20-day volume baseline.               
      22 +    hist = hist[(hist["Volume"] > 0) & hist["Close"].notna()]  
      23 +    if hist.empty:                                             
      24 +        return []                                              
      25      prev_close = hist["Close"].shift(1)
      26      pct = (hist["Close"] / prev_close - 1.0) * 100.0
      27      avg20 = hist["Volume"].shift(1).rolling(20).mean()

  Ran 1 shell command (ctrl+o to expand)

● Prices fixed, no failures. Now rebuilding the snapshot:

  Read 1 file, ran 1 shell command (ctrl+o to expand)

● Pipeline ran end to end. Let me verify the new snapshot:

  Ran 1 shell command (ctrl+o to expand)

● Snapshot is now fresh — latest filing 12 Nov 20:23 IST, ingest.last_error:
  None. The 24h window will no longer be empty.

  Now the /health endpoint:

● Write(frontend\app\health\route.ts)
  ⎿  Wrote 61 lines to frontend\app\health\route.ts
       1 import { readFile } from "node:fs/promises";
       2 import path from "node:path";
       3 import type { Snapshot } from "@/lib/types";
       4
       5 /**
       6  * Ingest health for the live site: when data last landed, how m
         uch of it there is, and
       7  * what the last ingestion error was.
       8  *
       9  * Prerendered at build time, which is the honest reading: the s
     … +53 lines (~2 KB) (ctrl+o to expand)

● Now add ingest to the Snapshot type, and make the data layer track why a live
  fetch failed:

● Update(frontend\lib\types.ts)
  ⎿  Added 6 lines
       94  export interface Snapshot {
       95    generated_at: string;
       96    as_of: { prices: string | null; announcements: string | null
           ; last_session: string | null };
       97 +  /** Ingest health. Absent in snapshots built before this was
          + recorded. */                                                 
       98 +  ingest?: {                                                  
       99 +    last_ok_at: string | null;                                
      100 +    last_attempted_at: string | null;                         
      101 +    last_error: string | null;                                
      102 +  } | null;                                                   
      103    material_threshold: number;
      104    defaults: Settings;
      105    portfolio: Holding[];

● Update(frontend\lib\data.ts)
  ⎿  Added 9 lines, removed 1 line
      17    source: Source;
      18    error: string | null;
      19    refreshing: boolean;
      20 +  /**                                                          
      21 +   * Why we are not showing live data. "none" = no backend is c
         +onfigured, so the committed                                    
      22 +   * snapshot IS the current data and must not be labelled a st
         +ale fallback. Set to a reason                                  
      23 +   * only when a live fetch was actually attempted and failed. 
      24 +   */                                                          
      25 +  liveError: string | null;                                    
      26  }
      27  
      22 -let state: State = { data: null, source: "bundled", error: null
         -, refreshing: false };                                         
      28 +let state: State = {                                           
      29 +  data: null, source: "bundled", error: null, refreshing: false
         +, liveError: null,                                             
      30 +};                                                             
      31  let started = false;
      32  const listeners = new Set<() => void>();
      33  

● Update(frontend\lib\data.ts)
  ⎿  Added 8 lines, removed 3 lines
      59    try {
      60      const live = await fetchJson(`${API}/api/snapshot`, 45000);
      61      if (!state.data || live.generated_at > state.data.generated
          _at) {
      62 -      set({ data: live, source: "live", error: null });        
      62 +      set({ data: live, source: "live", error: null, liveError:
         + null });                                                      
      63 +    } else {                                                   
      64 +      set({ liveError: null });                                
      65      }
      64 -  } catch {                                                    
      65 -    // Backend asleep or down: keep showing the snapshot, which
         - is labelled with its time.                                    
      66 +  } catch (err) {                                              
      67 +    // Backend asleep or down: keep showing the snapshot, and r
         +ecord why, so the stamp can                                    
      68 +    // say "live check failed" instead of silently implying the
         + data is merely saved.                                         
      69 +    const e = err as Error;                                    
      70 +    set({ liveError: e.name === "AbortError" ? "backend did not
         + respond" : `backend returned ${e.message}` });                
      71    } finally {
      72      set({ refreshing: false });
      73    }

● Now the DataStamp — it currently always says "saved snapshot" even though no
  live fetch is ever attempted:

● Update(frontend\components\Shell.tsx)
  ⎿  Added 1 line, removed 1 line
      1  "use client";
      2  
      3  import type { ReactNode } from "react";
      4 -import { useSnapshot } from "@/lib/data";                       
      4 +import { apiBase, useSnapshot } from "@/lib/data";              
      5  import { dateTime } from "@/lib/format";
      6  import type { Snapshot } from "@/lib/types";
      7  

● Update(frontend\components\Shell.tsx)
  ⎿  Added 31 lines, removed 6 lines
      29    );
      30  }
      31  
      32 -export function DataStamp({ snap, source, refreshing }: { snap:
         - Snapshot; source: string; refreshing: boolean }) {            
      33 -  const at = snap.as_of.announcements ?? snap.generated_at;    
      32 +/**                                                            
      33 + * The time shown is the last successful ingestion, not when th
         +e file was written, so a run                                   
      34 + * that failed to reach the exchange cannot advance it.        
      35 + *                                                             
      36 + * "saved snapshot" is reserved for a live fetch that genuinely
         + failed, and carries the                                       
      37 + * reason. With no backend configured the committed snapshot IS
         + the current data — the                                        
      38 + * scheduled job refreshes it twice a day — so calling it a fal
         +lback would be a lie.                                          
      39 + */                                                            
      40 +export function DataStamp({ snap, source, refreshing, liveError
         + }: {                                                          
      41 +  snap: Snapshot; source: string; refreshing: boolean; liveErro
         +r?: string | null;                                             
      42 +}) {                                                           
      43 +  const at = snap.ingest?.last_ok_at ?? snap.as_of.announcement
         +s ?? snap.generated_at;                                        
      44 +  const ingestError = snap.ingest?.last_error;                 
      45 +                                                               
      46 +  let label: string;                                           
      47 +  if (source === "live") label = "live";                       
      48 +  else if (liveError) label = `saved snapshot · ${liveError}`; 
      49 +  else if (!apiBase) label = "refreshed twice daily";          
      50 +  else label = "saved snapshot";                               
      51 +                                                               
      52    return (
      35 -    <p className="num text-[11px] text-faint">                 
      36 -      Data as of {dateTime(at)} IST · {source === "live" ? "liv
         -e" : "saved snapshot"}                                         
      37 -      {refreshing ? " · checking for newer…" : ""}             
      38 -    </p>                                                       
      53 +    <>                                                         
      54 +      <p className="num text-[11px] text-faint">               
      55 +        Data as of {dateTime(at)} IST · {label}                
      56 +        {refreshing ? " · checking for newer…" : ""}           
      57 +      </p>                                                     
      58 +      {ingestError && (                                        
      59 +        <p className="num text-[11px] text-faint">             
      60 +          Last ingestion reported: {ingestError}               
      61 +        </p>                                                   
      62 +      )}                                                       
      63 +    </>                                                        
      64    );
      65  }
      66  

● Update(frontend\components\Shell.tsx)
  ⎿  Added 5 lines, removed 3 lines
      66  
      67  /** Loading, error and ready states in one place, so every scre
          en handles all three. */
      68  export function WithSnapshot({ children }: {
      69 -  children: (snap: Snapshot, meta: { source: string; refreshing
         -: boolean }) => ReactNode;                                     
      69 +  children: (snap: Snapshot, meta: {                           
      70 +    source: string; refreshing: boolean; liveError: string | nu
         +ll;                                                            
      71 +  }) => ReactNode;                                             
      72  }) {
      71 -  const { data, error, source, refreshing } = useSnapshot();   
      72 -  if (data) return <>{children(data, { source, refreshing })}</
         ->;                                                             
      73 +  const { data, error, source, refreshing, liveError } = useSna
         +pshot();                                                       
      74 +  if (data) return <>{children(data, { source, refreshing, live
         +Error })}</>;                                                  
      75    if (error) {
      76      return (
      77        <div className="card p-4 text-[14px]">

  Searched for 1 pattern (ctrl+o to expand)

● Let me thread liveError through the other two screens that show the stamp:

  Ran 1 shell command (ctrl+o to expand)

● Update(frontend\components\AlertsScreen.tsx)
  ⎿  Added 3 lines, removed 1 line
      73    );
      74  }
      75  
      76 -function Ready({ snap, source, refreshing }: { snap: Snapshot; 
         -source: string; refreshing: boolean }) {                       
      76 +function Ready({ snap, source, refreshing, liveError }: {      
      77 +  snap: Snapshot; source: string; refreshing: boolean; liveErro
         +r?: string | null;                                             
      78 +}) {                                                           
      79    const { settings, mutes } = usePrefs();
      80    const end = new Date(snap.as_of.announcements ?? snap.generat
          ed_at);
      81    const start = new Date(end.getTime() - LOOKBACK_DAYS * 86400_
          000);

● Update(frontend\components\AlertsScreen.tsx)
  ⎿  Added 1 line, removed 1 line
      114            No filings in your followed types this week. Choose 
           types in Settings.
      115          </p>
      116        )}
      117 -      <div className="mt-5"><DataStamp snap={snap} source={sou
          -rce} refreshing={refreshing} /></div>                         
      117 +      <div className="mt-5"><DataStamp snap={snap} source={sou
          +rce} refreshing={refreshing} liveError={liveError} /></div>   
      118      </>
      119    );
      120  }

● Update(frontend\components\SettingsScreen.tsx)
  ⎿  Added 3 lines, removed 1 line
      23    );
      24  }
      25  
      26 -function Ready({ snap, source, refreshing }: { snap: Snapshot; 
         -source: string; refreshing: boolean }) {                       
      26 +function Ready({ snap, source, refreshing, liveError }: {      
      27 +  snap: Snapshot; source: string; refreshing: boolean; liveErro
         +r?: string | null;                                             
      28 +}) {                                                           
      29    const prefs = usePrefs();
      30    const followed = prefs.settings.alert_categories;
      31    const mutes = Object.keys(prefs.mutes);

● Update(frontend\components\SettingsScreen.tsx)
  ⎿  Added 1 line, removed 1 line
       98          <p className="text-[13px] text-muted">
       99            {snap.portfolio.length} companies · {snap.announceme
           nts.length} filings stored · last session {snap.as_of.last_ses
           sion}
      100          </p>
      101 -        <div className="mt-1"><DataStamp snap={snap} source={s
          -ource} refreshing={refreshing} /></div>                       
      101 +        <div className="mt-1"><DataStamp snap={snap} source={s
          +ource} refreshing={refreshing} liveError={liveError} /></div> 
      102          <button type="button" disabled={triaged === 0} onClick
           ={() => update({ seen: {}, starred: {} })}
      103            className="mt-3 h-10 rounded-md border border-line p
           x-3 text-[13px] font-medium disabled:opacity-40">
      104            Clear seen and starred ({triaged})

● Now the core empty-state work. Let me check the date formatters available:
  Searched for 1 pattern (ctrl+o to expand)

● dayLabel is what I need. Now the empty-state rewrite:

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Added 1 line, removed 1 line
      3  import Link from "next/link";
      4  import { useMemo, useState } from "react";
      5  import { buildBrief, firedAlerts, headline, nearestBusyWindow, t
         ype Brief } from "@/lib/brief";
      6 -import { CATEGORY_LABEL, dateTime, direction, greeting, istDay, 
        -pct } from "@/lib/format";                                      
      6 +import { CATEGORY_LABEL, dateTime, dayLabel, direction, greeting
        +, istDay, pct } from "@/lib/format";                            
      7  import { update, usePrefs, type WindowKey } from "@/lib/store";
      8  import type { Snapshot } from "@/lib/types";
      9  import { FilingCard } from "./FilingCard";

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Added 18 lines, removed 2 lines
      113    );
      114  }
      115  
      116 -function Ready({ snap, source, refreshing }: { snap: Snapshot;
          - source: string; refreshing: boolean }) {                     
      116 +function Ready({ snap, source, refreshing, liveError }: {     
      117 +  snap: Snapshot; source: string; refreshing: boolean; liveErr
          +or?: string | null;                                           
      118 +}) {                                                          
      119    const prefs = usePrefs();
      120    const brief = useMemo(() => buildBrief(snap, prefs), [snap, 
           prefs]);
      119 -  const lines = useMemo(() => headline(brief, snap), [brief, s
          -nap]);                                                        
      121    const [showSeen, setShowSeen] = useState(false);
      122    const now = new Date();
      123    const empty = brief.material.length === 0 && brief.seen.leng
           th === 0;
      124    const wider = useMemo(() => (empty ? nearestBusyWindow(snap,
            prefs) : null), [empty, snap, prefs]);
      125    const widerLabel = WINDOWS.find((w) => w.key === wider)?.lab
           el;
      126 +  const windowLabel = WINDOWS.find((w) => w.key === prefs.wind
          +ow)?.label ?? "window";                                       
      127  
      128 +  // An evaluator may open this days after the last ingestion.
          + Rather than a blank page,                                    
      129 +  // widen to the nearest window that has something and say so
          +. The chosen window stays                                     
      130 +  // selected, so this explains itself instead of silently ove
          +rriding the choice.                                           
      131 +  const fallback = useMemo(                                   
      132 +    () => (wider ? buildBrief(snap, { ...prefs, window: wider 
          +}) : null),                                                   
      133 +    [wider, snap, prefs],                                     
      134 +  );                                                          
      135 +  const shown = fallback ?? brief;                            
      136 +  const lines = useMemo(() => headline(shown, snap), [shown, s
          +nap]);                                                        
      137 +  const latestFilingTs = useMemo(                             
      138 +    () => snap.announcements.reduce<string | null>((m, a) => (
          +m === null || a.ts > m ? a.ts : m), null),                    
      139 +    [snap],                                                   
      140 +  );                                                          
      141 +                                                              
      142    return (
      143      <>
      144        <header className="pb-3 pt-2">

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Added 21 lines, removed 4 lines
      144        <header className="pb-3 pt-2">
      145          <p className="text-[13px] font-medium text-accent">{gr
           eeting(now)}. Here is your brief.</p>
      146          <h1 className="display mt-1 text-[30px] leading-9">
      147 -          {brief.material.length + brief.seen.length === 0    
      147 +          {shown.material.length + shown.seen.length === 0    
      148              ? "Nothing needs you right now."
      149 -            : `${brief.material.length + brief.seen.length} of
          - ${brief.total} filings are worth your time.`}                
      149 +            : `${shown.material.length + shown.seen.length} of
          + ${shown.total} filings are worth your time.`}                
      150          </h1>
      151          <p className="num mt-1.5 text-[13px] text-muted">
      152 -          {snap.portfolio.length} companies · {dateTime(brief.
          -range.start.toISOString())} to {dateTime(brief.range.end.toISO
          -String())}                                                    
      152 +          {snap.portfolio.length} companies · {dateTime(shown.
          +range.start.toISOString())} to {dateTime(shown.range.end.toISO
          +String())}                                                    
      153          </p>
      154        </header>
      155  
      156        <WindowPicker snap={snap} />
      157  
      158 +      {fallback && (                                          
      159 +        <section aria-label="Window widened" className="mt-4 r
          +ounded-[18px] border border-line bg-sunken px-4 py-3.5">      
      160 +          <p className="text-[15px] font-medium leading-[23px]
          +">                                                            
      161 +            Nothing new in the last {windowLabel.toLowerCase()
          +}.                                                            
      162 +          </p>                                                
      163 +          <p className="mt-1 text-[13px] leading-5 text-muted"
          +>                                                             
      164 +            {latestFilingTs                                   
      165 +              ? <>The latest filings are from {dayLabel(latest
          +FilingTs)}. Showing the last {widerLabel?.toLowerCase()} inste
          +ad.</>                                                        
      166 +              : <>Showing the last {widerLabel?.toLowerCase()}
          + instead.</>}                                                 
      167 +          </p>                                                
      168 +          <button type="button" onClick={() => wider && update
          +({ window: wider })}                                          
      169 +            className="mt-3 h-9 rounded-md border border-line 
          +bg-surface px-3.5 text-[13px] font-medium">                   
      170 +            Keep the last {widerLabel?.toLowerCase()}         
      171 +          </button>                                           
      172 +        </section>                                            
      173 +      )}                                                      
      174 +                                                              
      175        {lines.length > 0 && (
      176          <section aria-label="Summary" className="mt-4 rounded-
           [18px] bg-sunken px-4 py-3.5">
      177            <p className="label mb-1">In short</p>
     ...
      179          </section>
      180        )}
      181  
      165 -      <Movers snap={snap} brief={brief} />                    
      182 +      <Movers snap={snap} brief={shown} />                    
      183  
      184        <section aria-label="Material filings" className="mt-4 s
           pace-y-3">
      185          {brief.material.map((c) => <FilingCard key={c.head.id}
            cluster={c} now={now} />)}

● Now the material list and the remaining sections:

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Added 13 lines, removed 17 lines
      182        <Movers snap={snap} brief={shown} />
      183  
      184        <section aria-label="Material filings" className="mt-4 s
           pace-y-3">
      185 -        {brief.material.map((c) => <FilingCard key={c.head.id}
          - cluster={c} now={now} />)}                                   
      186 -        {brief.material.length === 0 && (                     
      185 +        {shown.material.map((c) => <FilingCard key={c.head.id}
          + cluster={c} now={now} />)}                                   
      186 +        {shown.material.length === 0 && (                     
      187            <div className="rounded-[18px] border border-dashed 
           border-line px-4 py-8 text-center">
      188              <p className="text-[15px] font-medium">
      189 -              {brief.seen.length > 0 ? "You are caught up." : 
          -"Quiet stretch. Nothing material in this window."}            
      189 +              {shown.seen.length > 0 ? "You are caught up." : 
          +"Quiet stretch. Nothing material to show."}                   
      190              </p>
      191              <p className="mt-1 text-[13px] text-muted">
      192 -              {brief.total > 0                                
      193 -                ? `${brief.routineCount} routine filing${brief
          -.routineCount === 1 ? "" : "s"} below, none needing attention.
          -`                                                             
      194 -                : "No filings from your portfolio in this wind
          -ow."}                                                         
      192 +              {shown.total > 0                                
      193 +                ? `${shown.routineCount} routine filing${shown
          +.routineCount === 1 ? "" : "s"} below, none needing attention.
          +`                                                             
      194 +                : latestFilingTs                              
      195 +                  ? `No material filings from your portfolio. 
          +The latest on record is from ${dayLabel(latestFilingTs)}.`    
      196 +                  : "No filings from your portfolio yet."}    
      197              </p>
      196 -            {wider && (                                       
      197 -              <button type="button" onClick={() => update({ wi
          -ndow: wider })}                                               
      198 -                className="mt-4 h-10 rounded-md bg-ink px-4 te
          -xt-[13px] font-medium text-bg">                               
      199 -                Show the last {widerLabel}                    
      200 -              </button>                                       
      201 -            )}                                                
      198            </div>
      199          )}
      200        </section>
      201  
      206 -      {brief.seen.length > 0 && (                             
      202 +      {shown.seen.length > 0 && (                             
      203          <section className="mt-4">
      204            <button type="button" onClick={() => setShowSeen(!sh
           owSeen)} aria-expanded={showSeen}
      205              className="flex h-10 items-center gap-1 text-[13px
           ] font-medium text-muted">
      206              <ChevronIcon width={16} height={16} className={sho
           wSeen ? "rotate-180" : ""} />
      211 -            {brief.seen.length} seen                          
      207 +            {shown.seen.length} seen                          
      208            </button>
      213 -          {showSeen && <div className="space-y-3">{brief.seen.
          -map((c) => <FilingCard key={c.head.id} cluster={c} now={now} /
          ->)}</div>}                                                    
      209 +          {showSeen && <div className="space-y-3">{shown.seen.
          +map((c) => <FilingCard key={c.head.id} cluster={c} now={now} /
          +>)}</div>}                                                    
      210          </section>
      211        )}
      212  
      217 -      <Routine brief={brief} />                               
      213 +      <Routine brief={shown} />                               
      214  
      215        <footer className="mt-5 space-y-1">
      220 -        <DataStamp snap={snap} source={source} refreshing={ref
          -reshing} />                                                   
      216 +        <DataStamp snap={snap} source={source} refreshing={ref
          +reshing} liveError={liveError} />                             
      217          <p className="num text-[11px] text-faint">
      218            {snap.stats && snap.stats.calls > 0 ? (
      219              <>

● Let me typecheck and build:

  Ran 2 shell commands (ctrl+o to expand)

● The AGENTS.md warning is live — Next.js 16 with cacheComponents rejects route
  segment config. Let me read the docs:

  Searched for 2 patterns, listed 1 directory (ctrl+o to expand)

● Docs are explicit: replace dynamic = 'force-static' with a use cache helper.
  The age calculation must stay per-request, so I'll cache only the file read:

● Write(frontend\app\health\route.ts)
  ⎿  Added 51 lines, removed 32 lines
       6   * Ingest health for the live site: when data last landed, how 
          much of it there is, and
       7   * what the last ingestion error was.
       8   *
       9 - * Prerendered at build time, which is the honest reading: the 
         -snapshot only ever changes                                     
      10 - * by being committed, and that commit triggers a Vercel rebuil
         -d. So the file this reads at                                   
      11 - * build time is exactly the file the deployed site serves.    
       9 + * The snapshot read is cached because that file only ever chan
         +ges by being committed, and                                    
      10 + * the commit triggers a rebuild. The staleness age is computed
         + per request instead, so                                       
      11 + * "how old is this data" is answered at the time of asking rat
         +her than at build time.                                        
      12   */
      13 -export const dynamic = "force-static";                         
      14 -                                                               
      13  const STALE_AFTER_HOURS = 24;
      14  
      17 -export async function GET() {                                  
      15 +interface Facts {                                              
      16 +  ok: boolean;                                                 
      17 +  error?: string;                                              
      18 +  last_successful_ingest?: string | null;                      
      19 +  last_ingest_attempt?: string | null;                         
      20 +  last_error?: string | null;                                  
      21 +  item_count?: number;                                         
      22 +  material_count?: number;                                     
      23 +  latest_filing_ts?: string | null;                            
      24 +  last_trading_session?: string | null;                        
      25 +  prices_as_of?: string | null;                                
      26 +  snapshot_generated_at?: string;                              
      27 +  companies_tracked?: number;                                  
      28 +}                                                              
      29 +                                                               
      30 +async function snapshotFacts(): Promise<Facts> {               
      31 +  "use cache";                                                 
      32    let snap: Snapshot;
      33    try {
      34      const file = path.join(process.cwd(), "public", "snapshot.j
          son");
      35      snap = JSON.parse(await readFile(file, "utf-8")) as Snapsho
          t;
      36    } catch (err) {
      23 -    return Response.json(                                      
      24 -      { status: "error", error: `snapshot unreadable: ${(err as
         - Error).message}` },                                           
      25 -      { status: 500 },                                         
      26 -    );                                                         
      37 +    return { ok: false, error: `snapshot unreadable: ${(err as 
         +Error).message}` };                                            
      38    }
      39  
      29 -  const ingest = snap.ingest ?? null;                          
      30 -  const lastIngest = ingest?.last_ok_at ?? snap.as_of.announcem
         -ents ?? snap.generated_at;                                     
      31 -  const ageHours = lastIngest                                  
      32 -    ? (Date.now() - new Date(lastIngest).getTime()) / 3_600_000
      33 -    : null;                                                    
      34 -                                                               
      40    const items = snap.announcements ?? [];
      36 -  const latestFiling = items.reduce<string | null>(            
      37 -    (max, a) => (max === null || a.ts > max ? a.ts : max),     
      38 -    null,                                                      
      39 -  );                                                           
      41 +  return {                                                     
      42 +    ok: true,                                                  
      43 +    last_successful_ingest:                                    
      44 +      snap.ingest?.last_ok_at ?? snap.as_of.announcements ?? sn
         +ap.generated_at,                                               
      45 +    last_ingest_attempt: snap.ingest?.last_attempted_at ?? null
         +,                                                              
      46 +    last_error: snap.ingest?.last_error ?? null,               
      47 +    item_count: items.length,                                  
      48 +    material_count: items.filter((a) => a.score >= snap.materia
         +l_threshold).length,                                           
      49 +    latest_filing_ts: items.reduce<string | null>(             
      50 +      (max, a) => (max === null || a.ts > max ? a.ts : max),   
      51 +      null,                                                    
      52 +    ),                                                         
      53 +    last_trading_session: snap.as_of.last_session ?? null,     
      54 +    prices_as_of: snap.as_of.prices ?? null,                   
      55 +    snapshot_generated_at: snap.generated_at,                  
      56 +    companies_tracked: snap.portfolio?.length ?? 0,            
      57 +  };                                                           
      58 +}                                                              
      59  
      41 -  const lastError = ingest?.last_error ?? null;                
      60 +export async function GET() {                                  
      61 +  const facts = await snapshotFacts();                         
      62 +  if (!facts.ok) {                                             
      63 +    return Response.json({ status: "error", last_error: facts.e
         +rror }, { status: 500 });                                      
      64 +  }                                                            
      65 +                                                               
      66 +  const { ok: _ok, error: _error, ...rest } = facts;           
      67 +  const last = facts.last_successful_ingest;                   
      68 +  const ageHours = last ? (Date.now() - new Date(last).getTime(
         +)) / 3_600_000 : null;                                         
      69    const stale = ageHours !== null && ageHours > STALE_AFTER_HOU
          RS;
      70  
      71    return Response.json(
      72      {
      46 -      status: lastError ? "degraded" : stale ? "stale" : "ok", 
      47 -      last_successful_ingest: lastIngest,                      
      48 -      last_ingest_attempt: ingest?.last_attempted_at ?? null,  
      73 +      status: facts.last_error ? "degraded" : stale ? "stale" :
         + "ok",                                                         
      74 +      ...rest,                                                 
      75        ingest_age_hours: ageHours === null ? null : Math.round(a
          geHours * 10) / 10,
      50 -      last_error: lastError,                                   
      51 -      item_count: items.length,                                
      52 -      material_count: items.filter((a) => a.score >= snap.mater
         -ial_threshold).length,                                         
      53 -      latest_filing_ts: latestFiling,                          
      54 -      last_trading_session: snap.as_of.last_session ?? null,   
      55 -      prices_as_of: snap.as_of.prices ?? null,                 
      56 -      snapshot_generated_at: snap.generated_at,                
      57 -      companies_tracked: snap.portfolio?.length ?? 0,          
      76 +      stale_after_hours: STALE_AFTER_HOURS,                    
      77      },
      78      { headers: { "cache-control": "no-store" } },
      79    );

  Ran 1 shell command (ctrl+o to expand)

● Build succeeds, /health is dynamic (correct — age is per-request). Let me run
  it and verify:

  Ran 2 shell commands (ctrl+o to expand)

● /health works. Now let me verify the Brief page renders with fresh data in a
  real browser:

● Skill(anthropic-skills:built-in-browser)
  ⎿  Successfully loaded skill

● The built-in browser can't reach a localhost server I started. Let me verify
  the brief logic directly against the real module instead:

  Ran 2 shell commands (ctrl+o to expand)

● 24h window now has 11 filings (2 material) — no longer empty. Let me verify
  the new fallback path engages correctly using the old stale snapshot that
  reproduced the bug:

  Ran 1 shell command (ctrl+o to expand)

● Both diagnosis and fix verified: the old snapshot reproduces the exact blank
  page, and the fix shows 3d content with a banner instead. Let me run the test
  suites:

  Ran 2 shell commands (ctrl+o to expand)

● All 77 pass. Let me add a regression test for the NaN-close bug since it
  silently killed all prices:

  Searched for 1 pattern, read 1 file, listed 1 directory, ran 1 shell command (ctrl+o to expand)

● Let me do a real visual check with local Chrome:

● No browser tooling is available in this session, so I'll verify what I can
  from the server and be explicit about the gap.

  Ran 1 shell command (ctrl+o to expand)

● All routes return 200, no server errors. Let me stop the server:

  Ran 1 shell command (ctrl+o to expand)

● Now the docs. Let me check the README for where to note /health:

  Read 1 file, listed 1 directory (ctrl+o to expand)
● Update(README.md)
  ⎿  Added 12 lines, removed 4 lines
      165  - **Frontend:** Vercel, root directory `frontend`, redeployed 
           on every push to `main`.
      166  - **Backend:** `render.yaml` is a Render blueprint (free tier)
           . Set `GEMINI_API_KEY` there
      167    and `NEXT_PUBLIC_API_URL` on Vercel.
      168 -- **Scheduled ingestion:** `.github/workflows/ingest.yml` refr
          -eshes the snapshot after the                                  
      169 -  close and three more times a day, and commits it; the databa
          -se and document cache persist                                 
      170 -  between runs so nothing is processed twice. It is opt-in: ad
          -d a `GEMINI_API_KEY` repository                               
      171 -  secret, then set the repository variable `FINN_INGEST_ENABLE
          -D` to `true`.                                                 
      168 +- **Scheduled ingestion:** `.github/workflows/ingest.yml` refr
          +eshes the snapshot twice a day                                
      169 +  — 13:00 UTC (18:30 IST, after the close) and 18:00 UTC (23:3
          +0 IST) on weekdays — and commits                              
      170 +  it, which triggers the Vercel redeploy that puts it live. Th
          +e database and document cache                                 
      171 +  persist between runs so nothing is processed twice. Add a `G
          +EMINI_API_KEY` repository secret                              
      172 +  to get model-written cards; without it the run still refresh
          +es prices, filings and ranking,                               
      173 +  and results cards come from the screener fallback. Use **Act
          +ions → Ingest → Run workflow**                                
      174 +  to refresh on demand.                                       
      175 +- **Health check:** `GET /health` on the deployed site reports
          + `status` (`ok`, `stale` or                                   
      176 +  `degraded`), `last_successful_ingest`, `ingest_age_hours`, `
          +item_count`, `material_count`,                                
      177 +  `latest_filing_ts` and `last_error`. `status` is `stale` onc
          +e the last successful ingest is                               
      178 +  over 24h old and `degraded` when the last run recorded an er
          +ror, so a blocked exchange is                                 
      179 +  visible without opening the workflow log.                   
      180  
      181  ## Known limitations
      182  

● Update(README.md)
  ⎿  Added 8 lines, removed 3 lines
      180  
      181  ## Known limitations
      182  
      183 -- **Sources can block cloud IPs.** NSE and BSE are reachable f
          -rom a laptop; from GitHub or                                  
      184 -  Render they may refuse. Ingestion then keeps the previous sn
          -apshot, and live research for                                 
      185 -  a new ticker reports the failure. The six pre-built companie
          -s always work.                                                
      183 +- **Sources can block cloud IPs.** NSE is reachable from a lap
          +top; from GitHub or Render it                                 
      184 +  may refuse. Announcements now take NSE's whole-market feed i
          +n one request rather than 20                                  
      185 +  per-symbol calls, which gives it one chance to rate-limit in
          +stead of twenty, but a block is                               
      186 +  still possible. Ingestion then keeps the previous snapshot, 
          +records the reason in                                         
      187 +  `ingest.last_error`, and `/health` reports `degraded`. BSE i
          +s not a fallback: its API                                     
      188 +  answers 403 to datacenter and residential requests alike, wi
          +th or without session priming.                                
      189 +- **Stale-data empty state.** If the chosen window has no fili
          +ngs the Brief widens to the                                   
      190 +  nearest window that does and says so, rather than showing a 
          +blank page.                                                   
      191  - **Two results PDFs cannot be read.** HDFC Bank's file is tru
           ncated on NSE's own server and
      192    Deepak Nitrite's is an image-only scan; both cards use scree
           ner's table and say so. There
      193    is no OCR.

● Update(README.md)
  ⎿  Added 1 line, removed 1 line
      200  - **Free-tier limits.** The strong model's 20 requests a day r
           uns out quickly; the fallback
      201    keeps the app working on the cheap model.
      202  - **Stale snapshot between ingestion runs.** The Brief is as f
           resh as the last committed
      203 -  snapshot; its header shows the exact window.                
      203 +  snapshot; its header shows the exact window and the footer t
          +he last successful ingest.                                    
      204  - **Single user.** Preferences live in the browser; there are 
           no accounts.
      205  
      206  ## More

● Now the build log entry:

  Read 1 file (ctrl+o to expand)

● Let me review everything before committing:

  Ran 2 shell commands (ctrl+o to expand)

● One edge case: with the Custom window the banner would read "Nothing new in
  the last custom." Let me fix that:

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Added 3 lines, removed 1 line
      123    const empty = brief.material.length === 0 && brief.seen.leng
           th === 0;
      124    const wider = useMemo(() => (empty ? nearestBusyWindow(snap,
            prefs) : null), [empty, snap, prefs]);
      125    const widerLabel = WINDOWS.find((w) => w.key === wider)?.lab
           el;
      126 -  const windowLabel = WINDOWS.find((w) => w.key === prefs.wind
          -ow)?.label ?? "window";                                       
      126 +  const emptyWindowPhrase = prefs.window === "custom"         
      127 +    ? "Nothing new in the dates you picked."                  
      128 +    : `Nothing new in the last ${(WINDOWS.find((w) => w.key ==
          += prefs.window)?.label ?? "window").toLowerCase()}.`;         
      129  
      130    // An evaluator may open this days after the last ingestion.
            Rather than a blank page,
      131    // widen to the nearest window that has something and say so
           . The chosen window stays

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Added 1 line, removed 3 lines
      159  
      160        {fallback && (
      161          <section aria-label="Window widened" className="mt-4 r
           ounded-[18px] border border-line bg-sunken px-4 py-3.5">
      162 -          <p className="text-[15px] font-medium leading-[23px]
          -">                                                            
      163 -            Nothing new in the last {windowLabel.toLowerCase()
          -}.                                                            
      164 -          </p>                                                
      162 +          <p className="text-[15px] font-medium leading-[23px]
          +">{emptyWindowPhrase}</p>                                     
      163            <p className="mt-1 text-[13px] leading-5 text-muted"
           >
      164              {latestFilingTs
      165                ? <>The latest filings are from {dayLabel(latest
           FilingTs)}. Showing the last {widerLabel?.toLowerCase()} inste
           ad.</>

  Ran 1 shell command (ctrl+o to expand)

● Let me clean that up rather than leave discarded variables:

● Write(frontend\app\health\route.ts)
  ⎿  Added 18 lines, removed 19 lines
      13  const STALE_AFTER_HOURS = 24;
      14  
      15  interface Facts {
      16 -  ok: boolean;                                                 
      17 -  error?: string;                                              
      18 -  last_successful_ingest?: string | null;                      
      19 -  last_ingest_attempt?: string | null;                         
      20 -  last_error?: string | null;                                  
      21 -  item_count?: number;                                         
      22 -  material_count?: number;                                     
      23 -  latest_filing_ts?: string | null;                            
      24 -  last_trading_session?: string | null;                        
      25 -  prices_as_of?: string | null;                                
      26 -  snapshot_generated_at?: string;                              
      27 -  companies_tracked?: number;                                  
      16 +  last_successful_ingest: string | null;                       
      17 +  last_ingest_attempt: string | null;                          
      18 +  last_error: string | null;                                   
      19 +  item_count: number;                                          
      20 +  material_count: number;                                      
      21 +  latest_filing_ts: string | null;                             
      22 +  last_trading_session: string | null;                         
      23 +  prices_as_of: string | null;                                 
      24 +  snapshot_generated_at: string;                               
      25 +  companies_tracked: number;                                   
      26  }
      27  
      30 -async function snapshotFacts(): Promise<Facts> {               
      28 +async function snapshotFacts(): Promise<Facts | { unreadable: s
         +tring }> {                                                     
      29    "use cache";
      30    let snap: Snapshot;
      31    try {
      32      const file = path.join(process.cwd(), "public", "snapshot.j
          son");
      33      snap = JSON.parse(await readFile(file, "utf-8")) as Snapsho
          t;
      34    } catch (err) {
      37 -    return { ok: false, error: `snapshot unreadable: ${(err as 
         -Error).message}` };                                            
      35 +    return { unreadable: (err as Error).message };             
      36    }
      37  
      38    const items = snap.announcements ?? [];
      39    return {
      42 -    ok: true,                                                  
      40      last_successful_ingest:
      41        snap.ingest?.last_ok_at ?? snap.as_of.announcements ?? sn
          ap.generated_at,
      42      last_ingest_attempt: snap.ingest?.last_attempted_at ?? null
          ,
     ...
      56  
      57  export async function GET() {
      58    const facts = await snapshotFacts();
      62 -  if (!facts.ok) {                                             
      63 -    return Response.json({ status: "error", last_error: facts.e
         -rror }, { status: 500 });                                      
      59 +  if ("unreadable" in facts) {                                 
      60 +    return Response.json(                                      
      61 +      { status: "error", last_error: `snapshot unreadable: ${fa
         +cts.unreadable}` },                                            
      62 +      { status: 500 },                                         
      63 +    );                                                         
      64    }
      65  
      66 -  const { ok: _ok, error: _error, ...rest } = facts;           
      66    const last = facts.last_successful_ingest;
      67    const ageHours = last ? (Date.now() - new Date(last).getTime(
          )) / 3_600_000 : null;
      68    const stale = ageHours !== null && ageHours > STALE_AFTER_HOU
          RS;
     ...
      70    return Response.json(
      71      {
      72        status: facts.last_error ? "degraded" : stale ? "stale" :
           "ok",
      74 -      ...rest,                                                 
      73 +      ...facts,                                                
      74        ingest_age_hours: ageHours === null ? null : Math.round(a
          geHours * 10) / 10,
      75        stale_after_hours: STALE_AFTER_HOURS,
      76      },

  Ran 1 shell command (ctrl+o to expand)

● Clean lint and build. Let me verify /health once more against the final build,
  then commit:

  Ran 2 shell commands (ctrl+o to expand)

● Now committing. Let me check the repo's commit message style and whether prior
  commits carry attribution:

  Ran 3 shell commands (ctrl+o to expand)

● Committed. Pushing now, which triggers the Vercel deploy you asked to see:

  Ran 1 shell command (ctrl+o to expand)

● Pushed. Let me wait for Vercel to rebuild, then verify the live site:

  Ran 2 shell commands (ctrl+o to expand)

● While the deploy runs — I spotted a fourth fault. The workflow commits with
  [skip ci], and Vercel treats that as a skip token, which would block the very
  redeploy the commit is meant to trigger. Let me confirm:

● web-fetch(Confirm Vercel skip-deploy commit tokens)
  ⎿  Received 951 bytes

● Background command "until curl -s -m 20
https://enam-ai-engineer-assignment.vercel.app/health 2>/dev/null | grep -q
"last_successful_ingest"; do sleep 10; done; echo "live /health is up""
completed (exit code 0)

● Live site is up. Let me verify it:

  Ran 1 shell command (ctrl+o to expand)

● Live site now serves fresh data: status: ok, 294 filings, 0.2h old.

  Now let me remove the [skip ci] risk — the workflow has no push trigger, so
  that tag prevents nothing but may block the Vercel deploy that is the entire
  delivery mechanism:

● Update(.github\workflows\ingest.yml)
  ⎿  Added 5 lines, removed 1 line
      79            if git diff --cached --quiet; then
      80              echo "No change in the snapshot."
      81            else
      82 -            git commit -m "Refresh snapshot [skip ci]"         
      82 +            # No "[skip ci]" here. This workflow has no push tr
         +igger, so there is no loop to                                  
      83 +            # prevent, and several hosts (Vercel among them) re
         +ad that token as "skip the                                     
      84 +            # build" — which would stop the redeploy that is th
         +e only way the refreshed                                       
      85 +            # snapshot reaches the live site.                  
      86 +            git commit -m "Refresh snapshot"                   
      87              git push
      88            fi

  Ran 1 shell command (ctrl+o to expand)

● Let me record the environment constraint that cost time this session:

  Recalled 1 memory (ctrl+o to expand)
● The memory already covers gh being absent. One correction worth recording —
  the documented method for stopping next start was more complex than needed:

  Ran 1 shell command, wrote 1 memory (ctrl+o to expand)

● All five routes are live. Here's what I found and fixed.

  Diagnosis — four faults, each sufficient alone

  1. The scheduled job had never run, not once. The workflow was committed
  behind if: ${{ vars.FINN_INGEST_ENABLED == 'true' }}, and that repository
  variable was never set, so every trigger evaluated the guard and skipped.
  Proven from history, not inferred: git log --author=finn-ingest and git log
  --grep="Refresh snapshot" are both empty. A guard meant as temporary safety
  became the reason nothing ever refreshed.

  2. Every price fetch was failing with NOT NULL constraint failed:
  prices.close. Yahoo publishes the newest session's volume before its close
  settles, so 12 Nov returned Volume 13.7M with Close NaN. That row passed the
  existing Volume > 0 filter, and store_prices uses one executemany — so a
  single bad row failed the batch for all 20 symbols. This would have broken the
  job even with the guard removed.

  3. The empty 24h window was real, not a rendering bug. The window ends at the
  last successful fetch (10 Nov 23:50 IST) and the newest filing was 9 Nov 18:11
  IST, so the span genuinely held nothing. Replaying the old snapshot through
  the real buildBrief reproduces total=0, material=0, seen=0 exactly.

  4. [skip ci] on the snapshot commit. Vercel and others read that as "skip the
  build" — and that commit is the only way refreshed data reaches the site.
  Removed.

  On your BSE instruction: I couldn't follow it. api.bseindia.com returns 403
  from a residential IP, plain and with homepage priming. It isn't a usable
  fallback. Instead I cut the NSE block risk a different way — announcements now
  use NSE's whole-market feed in one request (17,479 rows, filtered to your 274
  locally) rather than 20 per-symbol calls, giving NSE one chance to rate-limit
  a datacenter IP instead of twenty. Prices come from Yahoo, which doesn't
  block datacenters.

  Live now

  /health returns status: "ok", 294 filings (up from 271 — the 23 from 11–12 Nov
  the stale snapshot was missing), ingest_age_hours: 0.2, last_error: null.
  Schedule is twice daily on weekdays, 13:00 and 18:00 UTC. Empty windows now
  widen to the nearest window with filings and say so. "saved snapshot" is
  reserved for a genuinely failed live fetch and carries the reason. 80 backend
  tests pass (3 new for the price bug). Recorded in docs/BUILD_LOG.md.

  Two things only you can do

  1. Trigger the run — gh isn't installed here and I have no token, so I
     refreshed the data locally and pushed instead. Use Actions → Ingest → Run
     workflow to confirm it runs green in CI. That's the one claim I haven't
     verified: whether NSE accepts a GitHub runner's IP. If it refuses, /health
     will say degraded with the reason rather than failing silently.
  2. Check Settings → Actions → General → Workflow permissions is "Read and
     write". If it's read-only, the job will run green but its git push will
     fail.

  I could not visually check the UI — no browser tooling was available this
  session, and the built-in browser can't reach a server I start. The window
  arithmetic and the empty-state fallback were verified by running the real
  buildBrief against both the old and new snapshots.

> /model claude-opus-5
  ⎿  Set model to claude-opus-5
  ⎿  [Image #1]
  ⎿  [Image #2]

> should this appaear on website

● Good catch — that line should now read "refreshed twice daily", not "saved
  snapshot". Let me check whether my new code actually reached the browser.

  Ran 2 shell commands (ctrl+o to expand)

● The new code is deployed (that chunk contains "refreshed twice daily"). So the
  browser is running something else. Let me check whether an API URL is baked
  in, which would explain the bare label:

  Ran 2 shell commands (ctrl+o to expand)

● Found the real cause: NEXT_PUBLIC_API_URL is set on Vercel to a Render
  backend. Let me check whether it's alive:

  Ran 1 shell command (ctrl+o to expand)

● Found it precisely. The Render backend is alive and returned generated_at
  identical to the bundled snapshot (both deploy from the repo I just pushed).
  So:

  - live fetch succeeds → data is not newer (it's equal) → source stays
    "bundled" → label falls through to "saved snapshot"

  That's wrong. The live check succeeded and confirmed the data is current.
  "saved snapshot" should mean the fetch failed. My fix had a gap:

● Update(frontend\lib\data.ts)
  ⎿  Added 5 lines, removed 5 lines
      58    set({ refreshing: true });
      59    try {
      60      const live = await fetchJson(`${API}/api/snapshot`, 45000);
      61 -    if (!state.data || live.generated_at > state.data.generated
         -_at) {                                                         
      62 -      set({ data: live, source: "live", error: null, liveError:
         - null });                                                      
      63 -    } else {                                                   
      64 -      set({ liveError: null });                                
      65 -    }                                                          
      61 +    // A reply that merely matches what we already have still c
         +onfirms the data is current,                                   
      62 +    // so the source is "live" either way. Only the payload is 
         +conditional: we swap it when                                   
      63 +    // the backend is genuinely ahead, and keep ours when it is
         + not.                                                          
      64 +    const newer = !state.data || live.generated_at > state.data
         +.generated_at;                                                 
      65 +    set({ data: newer ? live : state.data, source: "live", erro
         +r: null, liveError: null });                                   
      66    } catch (err) {
      67      // Backend asleep or down: keep showing the snapshot, and r
          ecord why, so the stamp can
      68      // say "live check failed" instead of silently implying the
           data is merely saved.

  Ran 2 shell commands (ctrl+o to expand)

● Pushed. The footer will read "live" once this deploys (~1 min) — the live
  check genuinely succeeds, it just had nothing newer to offer.

  One caveat for checking: Session 2 added a service worker, so hard-refresh
  (Ctrl+Shift+R) or you may be served the cached bundle.

  Now, the other line in your screenshot is a deliberate choice from an earlier
  session, so I don't want to pull it unilaterally:

● User answered Claude's questions:
  ⎿  · The footer also shows "Model cost of this data: $0.7923 · 9,51,664 tokens
     · 239 calls, 66 from cache". That's internal telemetry pointed at an end
     user. Was that the line you were asking about, and should it stay? → Remove
     it entirely

● Removing it.

● Update(frontend\components\BriefScreen.tsx)
  ⎿  Removed 13 lines
      214  
      215        <footer className="mt-5 space-y-1">
      216          <DataStamp snap={snap} source={source} refreshing={ref
           reshing} liveError={liveError} />
      217 -        <p className="num text-[11px] text-faint">            
      218 -          {snap.stats && snap.stats.calls > 0 ? (             
      219 -            <>                                                
      220 -              Model cost of this data:{" "}                   
      221 -              {snap.stats.cost_inr !== null ? `₹${snap.stats.c
          -ost_inr.toFixed(2)}`                                          
      222 -                : snap.stats.cost_usd !== null ? `$${snap.stat
          -s.cost_usd.toFixed(4)}` : "not priced"}                       
      223 -              {" · "}{snap.stats.tokens.toLocaleString("en-IN"
          -)} tokens · {snap.stats.calls} calls,{" "}                    
      224 -              {snap.stats.cached} from cache                  
      225 -            </>                                               
      226 -          ) : (                                               
      227 -            "Model cost of this data: ₹0. Classified by rules,
          - numbers computed in code."                                   
      228 -          )}                                                  
      229 -        </p>                                                  
      217        </footer>
      218      </>
      219    );

  Read 1 file, ran 1 shell command (ctrl+o to expand)

● Same telemetry appears on the Research screen. Applying your decision
  consistently — keeping the "Researched <date>" provenance, dropping the tokens
  and cost:

● Update(frontend\components\ResearchScreen.tsx)
  ⎿  Added 1 line, removed 2 lines
      77  
      78        <footer className="mt-5">
      79          <p className="num text-[11px] leading-4 text-faint">
      80 -          Researched {dayLabel(research.generated_at)} · {resea
         -rch.usage.tokens.toLocaleString("en-IN")} model tokens         
      81 -          {research.usage.cost_usd !== null ? ` · $${research.u
         -sage.cost_usd.toFixed(2)} at list price, free tier used` : ""} 
      80 +          Researched {dayLabel(research.generated_at)}         
      81          </p>
      82        </footer>
      83      </>

  Ran 3 shell commands (ctrl+o to expand)

● Two separate things were going on in that screenshot, and only one was the
  label.

  "saved snapshot" was a real bug — fixed. NEXT_PUBLIC_API_URL is set on Vercel
  to finn-api-j8z0.onrender.com, and that backend is up. It deploys from the
  same repo, so it answered with a generated_at identical to the bundled
  snapshot. My swap was gated on the reply being strictly newer, so an equal
  reply left the source as "bundled" and the label fell through to "saved
  snapshot" — the one phrase I'd reserved for a fetch that failed, displayed
  after a fetch that succeeded. A reply that matches what we hold still confirms
  the data is current, so a successful fetch now marks the source live and only
  the payload stays conditional. The footer will read "live".

  Worth noting: that backend's existence contradicts the README, which still
  says no backend is deployed. I left the README alone rather than guess — tell
  me if it should be updated.

  The cost line is removed, per your call. I also found the same telemetry in
  the Research screen footer and removed it there too for consistency, keeping
  "Researched <date>" since that's provenance rather than telemetry. The cost
  accounting itself is untouched — still recorded per task in the snapshot's
  stats block and documented in the README.

  When you check, hard-refresh (Ctrl+Shift+R) — Session 2 added a service
  worker, so a normal reload may serve you the cached bundle. That is also the
  most likely reason you saw the old label at first: the new code was already on
  the CDN when you screenshotted it.

  Still outstanding from the original work, and only you can do it: trigger
  Actions → Ingest → Run workflow to confirm NSE accepts a GitHub runner's IP,
  and check Settings → Actions → General → Workflow permissions is "Read and
  write" or the job's git push will fail.

● Background command "until curl -s -m 20
https://enam-ai-engineer-assignment.vercel.app/ 2>/dev/null | grep -q
"_next/static"; do sleep 8; done; S=/c/Users/paras/AppData/Local/Temp/claude/c7d
6defadcb357ab/88c42b83-f3c6-408e-be9c-2bdbf3ea9f82/scratchpad; curl -s -m 25
https://enam-ai-engineer-assignment.vercel.app/ -o $S/live2.html; for c in
$(grep -oE '/_next/static/[a-zA-Z0-9._/-]+\.js' $S/live2.html | sort -u); do
b=$(curl -s -m 25 "https://enam-ai-engineer-assignment.vercel.app$c"); echo "$b"
| grep -q "Model cost of this data" && echo "STILL PRESENT: $c"; done; echo
"cost-line check done"" completed (exit code 0)

  Read 1 file (ctrl+o to expand)

● My wait condition was faulty — it matched any deploy, so it checked the old
  one. Let me re-check now:

  Ran 1 shell command (ctrl+o to expand)

● Confirmed deployed (new chunk hash). Let me verify the label logic itself
  shipped correctly:

  Ran 1 shell command (ctrl+o to expand)

● Both changes are confirmed live on the deployed bundle:

  Swap logic — source:"live" is now set on any successful fetch, with only the
  payload conditional (data: t ? e : a.data). That's the fix. The failure branch
  still sets liveError with a reason, as intended.

  Cost line — gone from every chunk the live page loads. Verified across all 8
  chunks, not just assumed from the build.

  So the footer should now read Data as of 13 Nov, 02:36 IST · live. One
  correction to what I told you earlier: I said it would show "refreshed twice
  daily" — that branch only applies when no backend is configured, and yours is.
  Since the Render backend answers, you get "live", which is the more accurate
  label anyway.

  Hard-refresh (Ctrl+Shift+R) to get past the service worker.

  Two things still only you can do: trigger Actions → Ingest → Run workflow to
  confirm NSE accepts a GitHub runner's IP, and confirm Settings → Actions →
  General → Workflow permissions is "Read and write", or the job's git push will
  fail. Also flagging again that the README says no backend is deployed, which
  the live Render API contradicts — say the word and I'll correct it.

> update the readme also

● Let me gather the facts first so the README is accurate rather than guessed.

  Searched for 1 pattern, read 1 file (ctrl+o to expand)
● The backend already has its own /api/health. Let me check what it returns and
  whether the live one actually works, so I document both accurately:

  Ran 1 shell command (ctrl+o to expand)

● Key detail: has_db: false — the Render instance has no database. Let me
  confirm what that means for its endpoints:

  Read 1 file (ctrl+o to expand)

● Now I have the accurate picture: the Render instance has no DB, so
  load_snapshot() falls back to the committed snapshot — the same file the
  frontend bundles. That's precisely why its generated_at matched and triggered
  the label bug. Let me find every README claim about the backend:

  Searched for 1 pattern (ctrl+o to expand)

● Update(README.md)
  ⎿  Added 11 lines, removed 2 lines
      163  ## Deployment
      164  
      165  - **Frontend:** Vercel, root directory `frontend`, redeployed 
           on every push to `main`.
      166 -- **Backend:** `render.yaml` is a Render blueprint (free tier)
          -. Set `GEMINI_API_KEY` there                                  
      167 -  and `NEXT_PUBLIC_API_URL` on Vercel.                        
      166 +- **Backend:** live at `https://finn-api-j8z0.onrender.com`, d
          +eployed from `render.yaml`                                    
      167 +  (Render free tier), with `NEXT_PUBLIC_API_URL` pointing at i
          +t on Vercel. It exists for Ask                                
      168 +  FINN and building research for a ticker that is not pre-buil
          +t — the things that need a                                    
      169 +  model key and network at request time.                      
      170 +  It is **not** a fresher source of the Brief. The free instan
          +ce has no persistent disk, so                                 
      171 +  `GET /api/health` reports `has_db: false` and `load_snapshot
          +()` falls back to the committed                               
      172 +  `data/snapshot.json` — the same file the frontend already bu
          +ndles. The app asks it for a                                  
      173 +  newer snapshot on load and keeps its own when the answer mat
          +ches, which is the normal case.                               
      174 +  Ingestion is GitHub Actions' job, never the API's: the API n
          +ever calls an exchange during a                               
      175 +  request. Free instances also sleep after inactivity, so the 
          +first call can take ~50s; the                                 
      176 +  app renders the bundled snapshot meanwhile and never blocks 
          +on it.                                                        
      177  - **Scheduled ingestion:** `.github/workflows/ingest.yml` refr
           eshes the snapshot twice a day
      178    — 13:00 UTC (18:30 IST, after the close) and 18:00 UTC (23:3
           0 IST) on weekdays — and commits
      179    it, which triggers the Vercel redeploy that puts it live. Th
           e database and document cache

● Now let me disambiguate the two health endpoints, since there are now one on
  each service:

  Read 1 file (ctrl+o to expand)

● Update(README.md)
  ⎿  Added 8 lines, removed 5 lines
      181    to get model-written cards; without it the run still refresh
           es prices, filings and ranking,
      182    and results cards come from the screener fallback. Use **Act
           ions → Ingest → Run workflow**
      183    to refresh on demand.
      184 -- **Health check:** `GET /health` on the deployed site reports
          - `status` (`ok`, `stale` or                                   
      185 -  `degraded`), `last_successful_ingest`, `ingest_age_hours`, `
          -item_count`, `material_count`,                                
      186 -  `latest_filing_ts` and `last_error`. `status` is `stale` onc
          -e the last successful ingest is                               
      187 -  over 24h old and `degraded` when the last run recorded an er
          -ror, so a blocked exchange is                                 
      188 -  visible without opening the workflow log.                   
      184 +- **Health checks:** two, answering different questions.      
      185 +  - [`/health`](https://enam-ai-engineer-assignment.vercel.app
          +/health) on the site asks *is                                 
      186 +    the data current?* — `status` (`ok`, `stale` or `degraded`
          +), `last_successful_ingest`,                                  
      187 +    `ingest_age_hours`, `item_count`, `material_count`, `lates
          +t_filing_ts` and `last_error`.                                
      188 +    `stale` once the last successful ingest is over 24h old, `
          +degraded` when the last run                                   
      189 +    recorded an error, so a blocked exchange shows without ope
          +ning the workflow log.                                        
      190 +  - `/api/health` on the Render API asks *is the API up?* — `o
          +k`, `has_db`, `has_snapshot`.                                 
      191 +    It says nothing about data freshness; `/health` is the one
          + to check for that.                                           
      192  
      193  ## Known limitations
      194  

● Let me fix the now-stale test count and check the intro section:

  Searched for 1 pattern, read 1 file (ctrl+o to expand)

● Update(README.md)
  ⎿  Added 1 line, removed 1 line
      157  `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.
           local`.
      158  
      159  - Research a ticker from the command line: `python ingest/rese
           arch.py TATAPOWER`
      160 -- Tests (77, all offline): `cd backend && python -m pytest -q`
      160 +- Tests (80, all offline): `cd backend && python -m pytest -q`
          + (must be run from `backend/`)                                
      161  - Check which models a key can reach: `cd backend && python -m
            finn.llm --check`
      162  
      163  ## Deployment

● Update(README.md)
  ⎿  Added 3 lines
      25     ₹6,700–7,000 cr one call later: Moved the goalposts.
      26  6. **Ask FINN** on any researched company. Every sentence carri
          es its source page; ask
      27     something the filings cannot answer and it says "Not disclos
          ed in the sources."
      28 +7. **[`/health`](https://enam-ai-engineer-assignment.vercel.app
         +/health)** to see how current                                  
      29 +   the data is: last successful ingest, how many hours ago, fil
         +ing counts, and the last                                       
      30 +   ingestion error if there was one.                           
      31  
      32  ## The product point of view
      33  

  Read 1 file (ctrl+o to expand)

● Update(README.md)
  ⎿  Added 3 lines, removed 1 line
      213    appointments, and FINN shows it when present. The web-search
            enrichment is not built.
      214  - **Push is in-app.** There is no Telegram or web-push channel
           , and no voice query.
      215  - **Free-tier limits.** The strong model's 20 requests a day r
           uns out quickly; the fallback
      216 -  keeps the app working on the cheap model.                   
      216 +  keeps the app working on the cheap model. The Render instanc
          +e sleeps after inactivity, so                                 
      217 +  the first Ask FINN or first-time research build after a quie
          +t spell waits ~50s for it to                                  
      218 +  wake. The Brief, Alerts and pre-built research never wait on
          + it.                                                          
      219  - **Stale snapshot between ingestion runs.** The Brief is as f
           resh as the last committed
      220    snapshot; its header shows the exact window and the footer t
           he last successful ingest.
      221  - **Single user.** Preferences live in the browser; there are 
           no accounts.

● Let me verify the claims I've written are actually true before committing —
  particularly the sleep behaviour and that the frontend genuinely doesn't block
  on the API:

  Ran 1 shell command (ctrl+o to expand)

● Both claims verified: the bundled snapshot renders first and the API call
  happens after, and CORS is correctly scoped to the Vercel origin. But one
  number I wrote is optimistic — the client aborts at 45s while a Render cold
  start can exceed that. Let me make that honest:

● Update(README.md)
  ⎿  Added 6 lines, removed 3 lines
      213    appointments, and FINN shows it when present. The web-search
            enrichment is not built.
      214  - **Push is in-app.** There is no Telegram or web-push channel
           , and no voice query.
      215  - **Free-tier limits.** The strong model's 20 requests a day r
           uns out quickly; the fallback
      216 -  keeps the app working on the cheap model. The Render instanc
          -e sleeps after inactivity, so                                 
      217 -  the first Ask FINN or first-time research build after a quie
          -t spell waits ~50s for it to                                  
      218 -  wake. The Brief, Alerts and pre-built research never wait on
          - it.                                                          
      216 +  keeps the app working on the cheap model. The Render instanc
          +e sleeps after inactivity and                                 
      217 +  can take ~50s to wake, which is longer than the app's 45s li
          +ve-snapshot timeout — so the                                  
      218 +  first load after a quiet spell may label the footer "saved s
          +napshot · backend did not                                     
      219 +  respond" even though nothing is broken. The Brief, Alerts an
          +d pre-built research render                                   
      220 +  from the bundled snapshot first and never wait on the API; o
          +nly Ask FINN and building a new                               
      221 +  ticker's research actually need it awake.                   
      222  - **Stale snapshot between ingestion runs.** The Brief is as f
           resh as the last committed
      223    snapshot; its header shows the exact window and the footer t
           he last successful ingest.
      224  - **Single user.** Preferences live in the browser; there are 
           no accounts.

● Update(README.md)
  ⎿  Added 2 lines, removed 2 lines
      175    `data/snapshot.json` — the same file the frontend already bu
           ndles. The app asks it for a
      176    newer snapshot on load and keeps its own when the answer mat
           ches, which is the normal case.
      177    Ingestion is GitHub Actions' job, never the API's: the API n
           ever calls an exchange during a
      178 -  request. Free instances also sleep after inactivity, so the 
          -first call can take ~50s; the                                 
      179 -  app renders the bundled snapshot meanwhile and never blocks 
          -on it.                                                        
      178 +  request. Free instances also sleep after inactivity and can 
          +take ~50s to wake; the app                                    
      179 +  renders the bundled snapshot first and never blocks on the A
          +PI.                                                           
      180  - **Scheduled ingestion:** `.github/workflows/ingest.yml` refr
           eshes the snapshot twice a day
      181    — 13:00 UTC (18:30 IST, after the close) and 18:00 UTC (23:3
           0 IST) on weekdays — and commits
      182    it, which triggers the Vercel redeploy that puts it live. Th
           e database and document cache

  Ran 2 shell commands (ctrl+o to expand)

● README updated and pushed. The substantive correction is that the Render API
  isn't what the README implied:

  It's live, but it is not a fresher source of Brief data. The free instance has
  no persistent disk, so /api/health reports has_db: false and load_snapshot()
  falls back to the committed data/snapshot.json — the same file the frontend
  already bundles. That's why its generated_at matched and triggered the label
  bug earlier: an equal reply is the normal case here, not a fault. Its actual
  job is Ask FINN and building research for a ticker that isn't pre-built, the
  two things needing a model key and network at request time. Ingestion stays
  GitHub Actions' job; the API never calls an exchange during a request.

  I verified rather than assumed: all five API endpoints return 200, CORS is
  correctly scoped to the Vercel origin, and the frontend renders the bundled
  snapshot before it touches the API.

  Also fixed:
  - The two health endpoints are now told apart — /health on the site answers
    "is the data current?", /api/health on Render answers "is the API up?" and
    says nothing about freshness.
  - An honest note on cold starts. Render takes ~50s to wake, which is longer
    than the client's 45s timeout, so the first load after a quiet spell can
    show "saved snapshot · backend did not respond" with nothing actually
    broken. Better documented than mistaken for a regression during a demo.
  - Test count 77 → 80, with the note that pytest must run from backend/.

  Unchanged and still true: the claim that every screen except Ask FINN and
  first-time research works with no backend at all.

  The two items only you can do are still open — triggering Actions → Ingest →
  Run workflow to find out whether NSE accepts a GitHub runner's IP, and
  confirming Workflow permissions is "Read and write".