"""Stage 1 of classification: deterministic rules. Free, instant, explainable.

Each rule looks at the exchange's own category (`exch`) and the filing's free-text
subject (`subj`). Rules are ordered: the first match wins, so specific rules sit
above general ones. Anything no rule claims is returned as AMBIGUOUS and goes to
the cheap LLM in stage 2 (see llm_classify.py).

A rule may also set a `kind`: a finer label inside a category that ranking uses to
demote paperwork (a newspaper ad about results is `results`, but nobody needs it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Verdict:
    category: str
    rule: str
    kind: str | None = None


@dataclass(frozen=True)
class Rule:
    name: str
    category: str
    exch: str | None = None      # regex on the exchange category
    subj: str | None = None      # regex on the subject text
    kind: str | None = None

    def matches(self, exch: str, subj: str) -> bool:
        if self.exch and not re.search(self.exch, exch, re.I):
            return False
        if self.subj and not re.search(self.subj, subj, re.I):
            return False
        return True


RESULTS_TEXT = r"financial results?|results? for the (quarter|period|year|half)"

RULES: list[Rule] = [
    # --- paperwork about results: still `results`, but demoted by kind -----------------
    Rule("results_newspaper_ad", "results", exch=r"newspaper", subj=RESULTS_TEXT, kind="newspaper_ad"),
    Rule("results_newspaper_ad_subj", "results", subj=r"newspaper.*(" + RESULTS_TEXT + ")", kind="newspaper_ad"),
    Rule("newspaper_other", "unclassified", exch=r"newspaper"),
    Rule("newspaper_other_subj", "unclassified", subj=r"newspaper (publication|advertisement)"),

    # --- earnings call vs investor meetings ---------------------------------------------
    Rule("call_transcript", "earnings_call", subj=r"transcript", kind="transcript"),
    Rule("call_recording", "earnings_call", subj=r"recording|audio|video link|webcast"),
    Rule("call_notice", "earnings_call",
         subj=r"(earnings|conference|con\.?|results?) call|concall|earnings (conference|webinar)"),
    Rule("investor_meet", "investor_meetings", exch=r"analysts?/institutional investor"),
    Rule("investor_meet_subj", "investor_meetings",
         subj=r"analyst\(?s?\)?\s*/\s*investor|investor (conference|meet)|schedule of (meet|analyst)|non-deal road ?show"),

    # --- results --------------------------------------------------------------------------
    Rule("results_filing", "results", exch=r"outcome of board meeting|financial result", subj=RESULTS_TEXT,
         kind="filing"),
    Rule("results_presentation", "results", exch=r"investor presentation", kind="deck"),
    Rule("results_exch", "results", exch=r"financial result", kind="filing"),
    Rule("results_report", "results", subj=r"(quarterly report|shareholders?.? letter|presentation).*(" + RESULTS_TEXT + ")",
         kind="deck"),
    Rule("results_presentation_subj", "results", subj=r"(results?|analyst|earnings) presentation", kind="deck"),
    Rule("results_board_intimation", "results", exch=r"board meeting intimation", subj=RESULTS_TEXT,
         kind="intimation"),

    # --- management change ----------------------------------------------------------------
    Rule("auditor_resign", "management_change", subj=r"resignation of (statutory )?auditor"),
    Rule("auditor_change", "unclassified", exch=r"change in auditor"),
    Rule("mgmt_exch", "management_change",
         exch=r"change in (management|director)|appointment|resignation|cessation|retirement"),
    Rule("mgmt_subj", "management_change",
         subj=r"(appoint|resign|cessation|retire|step(s|ped)? down).{0,80}"
              r"(director|chief|ceo|cfo|md\b|managing|company secretary|kmp|key managerial|chairman|chairperson)"),

    # --- litigation / regulatory ----------------------------------------------------------
    Rule("litigation_exch", "litigation",
         exch=r"action\(s\) (taken|initiated)|orders? passed|insolvency|litigation|dispute"),
    Rule("litigation_subj", "litigation",
         subj=r"\b(nclt|nclat|penalty|show cause|gst order|tax (demand|order)|demand order|court order|"
              r"arbitration|sebi order|adjudicat|fine imposed|warning letter)\b"),

    # --- M&A ------------------------------------------------------------------------------
    Rule("mna_exch", "M&A", exch=r"acquisition|amalgamation|merger|sale or disposal|restructuring|joint venture"),
    Rule("mna_subj", "M&A",
         subj=r"\b(acqui(re|sition)|amalgamation|merger|demerger|divest|joint venture|slump sale|"
              r"scheme of arrangement|stake (sale|purchase)|incorporation of (a )?(wholly|subsidiary))"),

    # --- fund raise -----------------------------------------------------------------------
    Rule("esop_allotment", "unclassified", exch=r"esop|allotment", subj=r"esop|esps|esos|stock option"),
    Rule("esop_exch", "unclassified", exch=r"esop"),
    Rule("esop_grant", "unclassified", subj=r"grant of [\d,]+ (stock )?(options|rsus?|units)"),
    Rule("cp_repayment", "fund_raise", subj=r"(repayment|redemption) of (commercial paper|ncd|debenture)",
         kind="repayment"),
    Rule("fund_raise_exch", "fund_raise", exch=r"allotment of securities|issue of securities|buy ?back|raising of funds"),
    Rule("fund_raise_subj", "fund_raise",
         subj=r"\b(qip|qualified institution|preferential (issue|allotment)|rights issue|buy-?back|"
              r"commercial paper|non[- ]convertible|ncds?|fund ?rais)"),
    Rule("fund_use_compliance", "unclassified",
         exch=r"monitoring agency|statement of deviation"),
    Rule("call_money", "unclassified", subj=r"call money|first and final call"),

    # --- pledging / insider ---------------------------------------------------------------
    Rule("pledge", "pledging", subj=r"\b(pledg|encumbr|invocation)"),
    Rule("insider", "insider_trading",
         subj=r"insider trading|regulation 7\(2\)|regulation 29|sast|takeover regulations|promoter.{0,40}(acquired|sold|purchas)"),
    Rule("trading_window", "unclassified", subj=r"trading window"),

    # --- credit rating --------------------------------------------------------------------
    Rule("rating", "credit_rating", exch=r"credit rating"),
    Rule("rating_subj", "credit_rating", subj=r"credit rating|rating (re)?affirm|\b(crisil|icra|care ratings|india ratings)\b"),

    # --- dividend / bonus / split ---------------------------------------------------------
    Rule("dividend_tds", "unclassified", subj=r"tds on .{0,20}dividend|tax deduct"),
    Rule("bonus_split", "bonus_split", subj=r"\bbonus (issue|shares)|stock split|sub-?division of (equity )?shares"),
    Rule("dividend", "dividend", exch=r"dividend"),
    Rule("dividend_subj", "dividend", subj=r"dividend"),
    Rule("record_date", "dividend", exch=r"record date"),

    # --- capex ----------------------------------------------------------------------------
    Rule("capex", "capex",
         subj=r"\b(capex|capital expenditure|capacity (expansion|addition)|new (plant|facility|manufacturing)|"
              r"greenfield|brownfield|commissioning|commercial production)"),

    # --- shareholder meetings -------------------------------------------------------------
    Rule("postal_ballot", "postal_ballot", subj=r"postal ballot"),
    Rule("agm_egm", "agm_egm",
         subj=r"\b(agm|egm|annual general meeting|extra-?ordinary general meeting)\b"),
    Rule("shareholder_meeting", "agm_egm", exch=r"shareholders? meeting"),

    # --- press release --------------------------------------------------------------------
    Rule("press_release", "press_release",
         exch=r"press release|bagging|receiving of orders|news verification|rumour verification|"
              r"clarification"),
    Rule("press_subj", "press_release",
         subj=r"press release|media release|order win|bagged|store opening|launch(es|ed)?\b|partnership|"
              r"collaborat"),

    # --- routine compliance ---------------------------------------------------------------
    Rule("compliance", "unclassified",
         exch=r"certificate|loss.*share|duplicate|esg|business responsibility|compliance"),
    Rule("compliance_subj", "unclassified",
         subj=r"registrar and share transfer|\brta\b|share certificate|certificate (pursuant|under)|"
              r"compliance certificate|technical issue|change in .{0,30}address|reminder notice"),
]

# "X has informed the Exchange about <exchange category>" restates the category and
# carries no information. Detect it so we do not spend an LLM call on an empty string.
BOILERPLATE = re.compile(
    r"^.{0,90}?has informed the exchange (about|regarding)\s*'*\s*(general updates|updates)\s*'*\.?$", re.I)


def classify(exch: str, subj: str) -> Verdict:
    exch, subj = exch or "", subj or ""
    for rule in RULES:
        if rule.matches(exch, subj):
            return Verdict(rule.category, rule.name, rule.kind)
    if BOILERPLATE.match(subj.strip()) or not subj.strip():
        return Verdict("unclassified", "uninformative_subject")
    return Verdict(AMBIGUOUS, "no_rule")
