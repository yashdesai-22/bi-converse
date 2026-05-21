"""Theme injection, hero banner, and reusable UI primitives."""
from __future__ import annotations

import streamlit as st

CSS = """
<style>
:root {
  --bg: #0B0F1A;
  --panel: #111827;
  --panel-2: #1F2937;
  --border: #1F2937;
  --text: #E5E7EB;
  --muted: #9CA3AF;
  --accent: #7C3AED;
  --accent-2: #06B6D4;
}

/* hide Streamlit chrome (but keep the sidebar collapse/expand control) */
#MainMenu, footer,
[data-testid="stDecoration"], [data-testid="stStatusWidget"] { display: none !important; }
header { background: transparent !important; }

/* keep the sidebar collapse/expand controls visible and clickable */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
  display: flex !important; visibility: visible !important; opacity: 1 !important;
  z-index: 999 !important;
}

/* tighter container */
.block-container { padding-top: 1.5rem !important; max-width: 1180px; }

/* typography */
html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  letter-spacing: -0.01em;
}
h1, h2, h3 { letter-spacing: -0.02em; }

/* hero */
.hero {
  background: radial-gradient(ellipse at top left, rgba(124,58,237,0.18), transparent 50%),
              radial-gradient(ellipse at bottom right, rgba(6,182,212,0.12), transparent 50%),
              linear-gradient(180deg, #111827 0%, #0B0F1A 100%);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 24px;
}
.hero-title {
  font-size: 30px; font-weight: 700; margin: 0 0 6px 0;
  background: linear-gradient(90deg, #fff 0%, #C4B5FD 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.hero-sub { color: var(--muted); font-size: 15px; margin: 0 0 16px 0; line-height: 1.5; }
.hero-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 500;
  background: rgba(124,58,237,0.12);
  border: 1px solid rgba(124,58,237,0.35);
  color: #C4B5FD;
}
.badge.cyan { background: rgba(6,182,212,0.10); border-color: rgba(6,182,212,0.35); color: #67E8F9; }
.badge.slate { background: rgba(148,163,184,0.10); border-color: rgba(148,163,184,0.30); color: #CBD5E1; }

/* card */
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  margin: 8px 0 14px 0;
}
.card-title { font-size: 13px; color: var(--muted); margin: 0 0 10px 0;
              text-transform: uppercase; letter-spacing: 0.08em; }

/* chat */
[data-testid="stChatMessage"] {
  background: var(--panel) !important;
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 18px !important;
}

/* sidebar */
[data-testid="stSidebar"] { background: #0A0E18; border-right: 1px solid var(--border); }
[data-testid="stSidebar"] .stButton > button {
  background: transparent; border: 1px solid var(--border);
  color: var(--text); text-align: left; font-weight: 400;
  transition: all 0.15s ease;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: rgba(124,58,237,0.10); border-color: var(--accent); color: #fff;
}

/* tables */
[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 10px; }

/* sidebar scroll blocks: size to viewport, split available space, scroll internally.
   Subtraction = ~150px reserved for sidebar header (~50) + 2 section headings (~30 each)
   + caption (~20) + paddings. Tweak if needed. */
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
  background: rgba(17, 24, 39, 0.5);
  margin-bottom: 10px !important;
  height: calc((100vh - 180px) / 2) !important;
  max-height: calc((100vh - 180px) / 2) !important;
  min-height: 160px !important;
  overflow-y: auto !important;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar { width: 8px; }
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar-thumb {
  background: #374151; border-radius: 4px;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar-track {
  background: transparent;
}

/* tighter sidebar headings to recover vertical space */
[data-testid="stSidebar"] h3 { margin: 6px 0 2px 0 !important; font-size: 14px; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { margin-bottom: 4px; }

/* code blocks */
[data-testid="stCode"] pre { background: #0A0E18 !important; border: 1px solid var(--border); }

/* expander */
[data-testid="stExpander"] {
  border: 1px solid var(--border) !important; border-radius: 10px !important;
  background: var(--panel);
}

/* chat input */
[data-testid="stChatInput"] textarea {
  background: var(--panel) !important;
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
}
</style>
"""


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, badges: list[tuple[str, str]]) -> None:
    """Render the hero banner. `badges` is a list of (label, color_class)."""
    badge_html = "".join(
        f'<span class="badge {cls}">{label}</span>' for label, cls in badges
    )
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-title">{title}</div>
          <p class="hero-sub">{subtitle}</p>
          <div class="hero-badges">{badge_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def card_open(title: str | None = None) -> None:
    if title:
        st.markdown(f'<div class="card"><div class="card-title">{title}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="card">', unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


ANSWER_CSS = """
<style>
.answer-block {
  background: linear-gradient(135deg, rgba(124,58,237,0.10), rgba(6,182,212,0.06));
  border: 1px solid rgba(124,58,237,0.30);
  border-radius: 16px;
  padding: 24px 28px;
  margin: 6px 0 14px 0;
}
.answer-kv { display: flex; flex-wrap: wrap; gap: 28px 36px; }
.answer-item { display: flex; flex-direction: column; gap: 4px; }
.answer-label {
  font-size: 11px; color: var(--muted, #9CA3AF);
  text-transform: uppercase; letter-spacing: 0.08em; font-weight: 500;
}
.answer-value {
  font-size: 28px; font-weight: 700; color: #fff;
  font-variant-numeric: tabular-nums;
}
.answer-value.text { font-size: 22px; }
.list-block {
  background: #111827; border: 1px solid #1F2937; border-radius: 12px;
  padding: 14px 18px; margin: 6px 0 14px 0;
}
.list-block ol { margin: 0; padding-left: 20px; }
.list-block li { padding: 4px 0; color: #E5E7EB; }
.list-block li::marker { color: #7C3AED; font-weight: 600; }
</style>
"""


def _format_value(v: object) -> tuple[str, bool]:
    """Return (display_string, is_numeric)."""
    if v is None:
        return ("—", False)
    if isinstance(v, bool):
        return (str(v), False)
    if isinstance(v, int):
        return (f"{v:,}", True)
    if isinstance(v, float):
        if v.is_integer():
            return (f"{int(v):,}", True)
        if abs(v) >= 1000:
            return (f"{v:,.2f}", True)
        return (f"{v:,.4g}", True)
    return (str(v), False)


def answer_block(row: dict) -> None:
    """Render a 1-row result as a labeled key/value answer card."""
    st.markdown(ANSWER_CSS, unsafe_allow_html=True)
    items = []
    for k, v in row.items():
        text, numeric = _format_value(v)
        cls = "" if numeric else " text"
        items.append(
            f'<div class="answer-item">'
            f'<span class="answer-label">{k}</span>'
            f'<span class="answer-value{cls}">{text}</span>'
            f"</div>"
        )
    st.markdown(
        f'<div class="answer-block"><div class="answer-kv">{"".join(items)}</div></div>',
        unsafe_allow_html=True,
    )


def list_block(values: list, label: str, limit: int = 50) -> None:
    """Render a single-column result as a numbered list."""
    st.markdown(ANSWER_CSS, unsafe_allow_html=True)
    rendered = values[:limit]
    items_html = "".join(f"<li>{_format_value(v)[0]}</li>" for v in rendered)
    more = (
        f'<div style="color:#9CA3AF;font-size:12px;margin-top:8px;">'
        f"…and {len(values) - limit} more</div>"
        if len(values) > limit
        else ""
    )
    st.markdown(
        f'<div class="list-block">'
        f'<div class="card-title" style="margin-bottom:8px;">{label}</div>'
        f"<ol>{items_html}</ol>{more}</div>",
        unsafe_allow_html=True,
    )
