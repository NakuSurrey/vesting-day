"""The page as first sent: the headline results and the recorded live runs, filled in on the server.

The web page fills these in with JavaScript from GET /evidence. A reader that does not run
JavaScript (a text browser, a screen reader in some modes, an AI agent fetching the page) would
otherwise see the layout with no results, so the same numbers go into the HTML here, from the
same committed logs, at request time. Nothing is typed in: change the logs and the page changes.
The script replaces all of it as soon as it runs.
"""

from __future__ import annotations

from html import escape
from typing import Any

SRC = '<p class="src" id="resultsSrc">Loading the recorded live runs...</p>'
FINDINGS = '<div id="findings"></div>'
RUNS = '<ol class="runs" id="runs"></ol>'


def _gbp(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return "GBP " + (f"{x:,.0f}" if abs(x) >= 1000 else f"{x:,.2f}")


def _gbp_short(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"GBP {x / 1e6:.1f}m" if x >= 1e6 else _gbp(x)


def _link(label: str, export: dict[str, Any] | None) -> tuple[str, str] | None:
    return (f"{label} ({export['rows']}, CSV)", export["url"]) if export and export.get("url") else None


def _finding(fig: str, sub: str, what: str, nxt: str, links: list[tuple[str, str] | None]) -> str:
    acts = "".join(f'<a class="dl" href="{escape(u)}">{escape(t)}</a> ' for t, u in (x for x in links if x))
    return (f'<div class="finding"><div class="fig">{escape(fig)}<small>{escape(sub)}</small></div>'
            f'<div><div class="what">{escape(what)}</div><div class="next">{escape(nxt)}</div></div>'
            + (f'<div class="acts">{acts}</div>' if acts else "") + "</div>")


def findings_html(ev: dict[str, Any]) -> str:
    h, c = ev.get("headline") or {}, ev.get("critic") or {}
    out = []
    if h.get("contracts"):
        k = h["contracts"]
        out.append(_finding(_gbp_short(k["value_gbp"]), f"{k['count']} contracts",
                            f"{k['count']} contracts end within {k['window_days']} days of vesting day with no extension date recorded past it; "
                            f"{k['shared_suppliers']} of their suppliers are also paid by another council.",
                            "decide novation, extension or planned expiry, largest first. The letter for the largest is held as "
                            f"{', '.join(k.get('drafts') or [])}; nothing is sent.",
                            [_link("Contract list", k.get("export"))]))
    if h.get("suppliers"):
        k = h["suppliers"]
        recalled = k.get("recalled") or []
        out.append(_finding(str(k["shared"]), "supplier pairs shared",
                            f"{k['shared']} supplier pairs are shared across the councils, {_gbp(k['spend_gbp'])} combined spend"
                            + (f"; resolved using remembered decision {', '.join(recalled)}" if recalled else "") + ".",
                            f"one contract instead of two or three, biggest spend first. {k['awaiting_human']} similar names wait for a person; each decision is remembered.",
                            [_link("Shared suppliers", k.get("export")), _link("Decision queue", k.get("queue_export"))]))
    if h.get("policy"):
        k = h["policy"]
        out.append(_finding(f"{k['differ']} of {k['clauses']}", "clauses differ",
                            f"{k['differ']} of {k['clauses']} Council Tax Support clauses differ between {' and '.join(k.get('councils') or [])}; "
                            f"{k['synthetic_differ']} of {k['synthetic_residents']} SYNTHETIC test residents would get a different answer on day one.",
                            f"agree one scheme before vesting day. The options note is held as {', '.join(k.get('drafts') or [])}.", []))
    if c.get("model_drafts"):
        out.append(_finding(f"{c['sent_back']} of {c['model_drafts']}", "drafts sent back",
                            f"Across the recorded live runs Nemotron wrote {c['model_drafts']} drafts; the Critic sent {c['sent_back']} back before anyone saw them.",
                            "every answer you see passed the Critic, or is the evidence-only template, badged as such.", []))
    return "".join(out)


def source_text(ev: dict[str, Any]) -> str | None:
    src = ev.get("headline_run")
    if not src:
        return None
    how = (f"{src.get('model')} via Meterless Nightshift, {src.get('model_calls_with_receipts')} signed receipts" if src.get("live")
           else "sample mode, no model")
    return (f"From the recorded live run {src['run_id']} ({(src.get('started') or '')[:10]}): \"{src.get('query')}\" - {how}. "
            "Read from the committed log; no number is typed into this page.")


def runs_html(ev: dict[str, Any]) -> str:
    items = []
    for r in reversed(ev.get("runs") or []):
        rid = escape(str(r["run_id"]))
        facts = (f"{r['run_id']} - {(r.get('started') or '')[:10]} - {r.get('trace_events')} steps, {r.get('zetaris_queries')} Zetaris queries, "
                 f"{r.get('model_calls_with_receipts')} Nemotron calls with receipts, {r.get('sent_back')} sent back")
        items.append(f'<li><div><div class="q">{escape(str(r.get("query") or r["run_id"]))}</div><div class="facts">{escape(facts)}</div></div>'
                     f'<div><a class="dl" href="/evidence/{rid}">Answer (JSON)</a> <a class="dl" href="/trace/{rid}">Steps (JSON)</a></div></li>')
    return "".join(items)


def prerender(html: str, ev: dict[str, Any]) -> str:
    """Fill the results, their source line and the live-run list into the page; plain ASCII, like the page."""
    src, found, runs = source_text(ev), findings_html(ev), runs_html(ev)
    if src and SRC in html:
        html = html.replace(SRC, f'<p class="src" id="resultsSrc">{escape(src)}</p>', 1)
    if found and FINDINGS in html:
        html = html.replace(FINDINGS, f'<div id="findings">{found}</div>', 1)
    if runs and RUNS in html:
        html = html.replace(RUNS, f'<ol class="runs" id="runs">{runs}</ol>', 1)
    return html.encode("ascii", "xmlcharrefreplace").decode("ascii")
