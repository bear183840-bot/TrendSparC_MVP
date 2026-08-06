"""Theme tokens for the TrendSparC Streamlit prototype."""

from __future__ import annotations


def dashboard_css(dark: bool, accent_theme: str = "orange") -> str:
    """`accent_theme` is a user-facing toggle ("orange" or "burgundy"), not
    tied to audience - both reference mockups (경영진=orange, 임원=burgundy)
    should be reachable regardless of who's asking."""
    if dark:
        colors = {
            "page": "#050505", "panel": "#0b0b0b", "panel2": "#131313",
            "sidebar": "#343434", "ink": "#f3f0e9", "muted": "#aaa69f",
            "line": "#76736d", "soft": "#242424", "shadow": "rgba(0,0,0,.34)",
        }
    else:
        colors = {
            "page": "#f7f7f5", "panel": "#ffffff", "panel2": "#fbfbfa",
            "sidebar": "#d7d7d7", "ink": "#202020", "muted": "#77736e",
            "line": "#aaa7a2", "soft": "#eeeeec", "shadow": "rgba(43,38,31,.10)",
        }
    if accent_theme == "burgundy":
        accent_colors = (
            {"accent": "#b5333f", "accent2": "#d97a4f", "teal": "#3f8a66"}
            if dark
            else {"accent": "#7a1f28", "accent2": "#b5502e", "teal": "#2f6b4f"}
        )
    else:
        accent_colors = (
            {"accent": "#f24a0a", "accent2": "#ff8a00", "teal": "#0c7884"}
            if dark
            else {"accent": "#f04408", "accent2": "#f08300", "teal": "#135b86"}
        )
    colors.update(accent_colors)
    return f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css');
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@700;800;900&display=swap');
    :root {{ --ts-page:{colors['page']}; --ts-panel:{colors['panel']}; --ts-panel2:{colors['panel2']};
      --ts-sidebar:{colors['sidebar']}; --ts-ink:{colors['ink']}; --ts-muted:{colors['muted']};
      --ts-line:{colors['line']}; --ts-soft:{colors['soft']}; --ts-accent:{colors['accent']};
      --ts-orange:{colors['accent2']}; --ts-teal:{colors['teal']}; --ts-shadow:{colors['shadow']}; }}
    html, body, [class*="css"] {{ font-family:"Pretendard Variable",Pretendard,"Noto Sans KR","Malgun Gothic",sans-serif; }}
    [data-testid="stAppViewContainer"] {{ background:var(--ts-page); color:var(--ts-ink); }}
    [data-testid="stHeader"] {{ background:transparent; }}
    [data-testid="stToolbar"] {{ right:1rem; }}
    .block-container {{ max-width:1720px; padding:.75rem 1.6rem 1rem; }}
    [data-testid="stSidebar"] {{ background:var(--ts-sidebar); border-right:0; }}
    [data-testid="stSidebar"] .block-container {{ padding:1.8rem 1.1rem; }}
    [data-testid="stSidebar"] * {{ color:var(--ts-ink); }}
    div[data-testid="stForm"] {{ max-width:1080px; margin:0 auto; border:0; background:transparent; padding:0; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stHorizontalBlock"] {{ padding:.55rem 1rem;
      margin-top:.65rem; border-radius:30px; background:color-mix(in srgb,var(--ts-soft) 92%,var(--ts-panel)); }}
    div[data-testid="stTextArea"] textarea {{ min-height:142px; padding:1.35rem 1.55rem; border:0;
      border-radius:30px; background:var(--ts-soft); color:var(--ts-ink); font-size:1.08rem;
      box-shadow:none; resize:none; }}
    div[data-testid="stTextArea"] textarea:focus {{ box-shadow:0 0 0 2px var(--ts-accent); }}
    [class*="st-key-intake_meta_row"] div[data-testid="stPopover"] button {{ border:0!important;
      border-radius:999px!important; background:var(--ts-accent)!important; padding:.4rem 1.2rem!important;
      box-shadow:0 4px 10px color-mix(in srgb,var(--ts-accent) 35%,transparent)!important;
      justify-content:center!important; min-height:auto!important; white-space:nowrap!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stPopover"] button * {{
      color:#fff!important; font-weight:800!important; font-size:1.05rem!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] div[data-baseweb="select"],
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] div[role="group"] {{
      border-radius:999px!important; background:var(--ts-accent)!important; padding:.4rem 1.2rem!important;
      box-shadow:0 4px 10px color-mix(in srgb,var(--ts-accent) 35%,transparent)!important; border:0!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] div[data-baseweb="select"] *,
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] div[role="group"] input {{
      background:transparent!important; border:0!important; box-shadow:none!important;
      color:#fff!important; font-weight:800!important; font-size:1.05rem!important;
      white-space:nowrap!important; overflow:visible!important; text-overflow:clip!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] input::placeholder {{
      color:#fff!important; opacity:1!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stPopover"] svg {{ fill:#fff!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] svg {{ fill:#fff!important; color:#fff!important; }}
    [class*="st-key-intake_meta_row"] div[data-testid="stSelectbox"] button {{
      background:transparent!important; border:0!important; }}
    [data-baseweb="popover"] [role="listbox"] {{ min-width:260px!important; border-radius:16px!important;
      padding:.4rem!important; box-shadow:0 16px 32px var(--ts-shadow)!important;
      border:1px solid var(--ts-line)!important; background:var(--ts-panel)!important; }}
    [data-baseweb="popover"] [role="option"] {{ font-family:"Pretendard Variable",Pretendard,sans-serif;
      font-size:.94rem!important; font-weight:600; padding:.62rem .85rem!important; border-radius:10px;
      white-space:nowrap; color:var(--ts-ink)!important; }}
    [data-baseweb="popover"] [role="option"]:hover {{ background:color-mix(in srgb,var(--ts-accent) 12%,var(--ts-panel))!important;
      color:var(--ts-accent)!important; }}
    [data-baseweb="popover"] [role="option"][aria-selected="true"] {{
      background:color-mix(in srgb,var(--ts-accent) 16%,var(--ts-panel))!important; color:var(--ts-accent)!important;
      font-weight:800; }}
    div[data-testid="stFormSubmitButton"] {{ margin-top:.9rem; }}
    div[data-testid="stFormSubmitButton"] button {{ min-height:56px; min-width:180px; border:0!important;
      border-radius:999px; background:var(--ts-accent); color:#fff; font-family:"Pretendard Variable",Pretendard,sans-serif!important;
      font-size:1.45rem!important; font-weight:900!important; letter-spacing:.02em;
      box-shadow:0 10px 22px color-mix(in srgb,var(--ts-accent) 45%,transparent); }}
    div[data-testid="stFormSubmitButton"] button p {{ font-size:1.45rem!important; font-weight:900!important; }}
    div[data-testid="stFormSubmitButton"] button:hover {{ background:color-mix(in srgb,var(--ts-accent) 85%,black); color:#fff;
      box-shadow:0 12px 26px color-mix(in srgb,var(--ts-accent) 55%,transparent); }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:var(--ts-line)!important;
      background:var(--ts-panel); border-radius:24px; box-shadow:none; }}
    .ts-wordmark {{ display:flex; align-items:flex-end; gap:0; color:var(--ts-ink); }}
    .ts-wordmark-text {{ font-family:"Quicksand","Pretendard Variable",Pretendard,sans-serif; font-size:2.15rem;
      line-height:.92; font-weight:500; letter-spacing:-.01em; }}
    .ts-word-1, .ts-word-2 {{ display:block; }}
    .ts-word-2 {{ margin-left:1.85em; }}
    .ts-mark {{ display:inline-block; width:78px; height:71px; transform:translateY(-8px);
      margin-left:-10px; }}
    .ts-mark svg {{ display:block; width:100%; height:100%; }}
    .ts-landing {{ min-height:43vh; display:flex; flex-direction:column; align-items:center;
      justify-content:flex-end; padding:3vh 0 2.1rem; text-align:center; }}
    .ts-landing .ts-wordmark {{ color:var(--ts-accent); }}
    .ts-landing .ts-wordmark-text {{ font-size:5.35rem; line-height:.78; }}
    .ts-landing .ts-mark {{ width:231px; height:210px; margin-left:-34px; transform:translateY(-10px); }}
    .ts-question-title {{ margin:1.6rem 0 0!important; font-family:"Pretendard Variable",Pretendard,sans-serif!important;
      font-size:clamp(1.5rem,2.4vw,2.35rem)!important; font-weight:600!important; letter-spacing:-.02em!important;
      color:var(--ts-ink)!important; }}
    .ts-compose-meta {{ max-width:980px; margin:.85rem auto 0; padding:.72rem 1rem; border-radius:22px;
      background:color-mix(in srgb,var(--ts-soft) 88%,var(--ts-panel)); color:var(--ts-muted);
      font-size:.9rem; }}
    .ts-header-row {{ display:flex; align-items:center; gap:1.3rem; margin:0 0 .45rem; }}
    .ts-top-question {{ flex:1; min-width:0; display:flex; align-items:center; gap:1rem; margin:0; padding:.68rem 1.3rem;
      border:3px solid var(--ts-accent); border-radius:999px; color:var(--ts-accent); font-size:1.1rem;
      font-weight:900; letter-spacing:-.02em;
      background:color-mix(in srgb,var(--ts-accent) 6%,var(--ts-panel)); }}
    .ts-top-question .search {{ font-size:1.6rem; flex:none; }}
    .ts-sk-badge {{ flex:none; display:inline-block; width:120px; height:94px; background:var(--ts-accent);
      -webkit-mask-image:var(--ts-sk-mask); mask-image:var(--ts-sk-mask);
      -webkit-mask-repeat:no-repeat; mask-repeat:no-repeat;
      -webkit-mask-size:contain; mask-size:contain;
      -webkit-mask-position:center; mask-position:center; }}
    /* Meta row - reference design 1a: small caps label + value, each on its
       own hairline underline rather than a floating inline row. */
    .ts-context-line {{ display:flex; gap:1.9rem; align-items:flex-end; margin:.35rem 1.4rem .75rem;
      color:var(--ts-ink); font-weight:750; flex-wrap:wrap; }}
    .ts-context-line span {{ display:flex; align-items:baseline; gap:.6rem; padding-bottom:.32rem;
      border-bottom:1px solid var(--ts-line); }}
    .ts-context-line span small {{ color:var(--ts-muted); font-size:.66rem; margin-right:0; font-weight:500;
      letter-spacing:.06em; }}
    .ts-summary-grid {{ display:grid; grid-template-columns:minmax(0,1fr) 210px; gap:1.2rem; align-items:stretch; }}
    /* Analysis Summary - reference design 1a's gradient panel with a fading
       rule under the heading instead of a full-width divider. */
    .ts-summary {{ padding:1.15rem 1.5rem 1.25rem; border-radius:10px; color:white;
      background:linear-gradient(135deg,var(--ts-accent),color-mix(in srgb,var(--ts-accent) 62%,#000)); }}
    .ts-summary h2 {{ margin:0 0 .55rem; padding-bottom:.4rem; border-bottom:0; color:white;
      font-size:1.18rem; font-weight:700; letter-spacing:-.01em; position:relative; }}
    .ts-summary h2::after {{ content:""; position:absolute; left:0; bottom:0; width:150px; height:1.5px;
      background:linear-gradient(90deg,rgba(255,255,255,.9),rgba(255,255,255,0)); }}
    .ts-summary p {{ margin:0; font-size:.95rem; line-height:1.62; font-weight:600; letter-spacing:-.01em;
      color:rgba(255,255,255,.95); display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical;
      overflow:hidden; }}
    .ts-signal-stack {{ display:grid; gap:.75rem; }}
    .ts-signal {{ padding:.6rem .85rem; border-bottom:1px solid var(--ts-accent); color:var(--ts-ink); }}
    .ts-signal small {{ color:var(--ts-muted); }} .ts-signal strong {{ float:right; color:var(--ts-orange); }}
    .ts-summary-compact {{ min-height:112px; max-height:128px; }}
    .ts-stat-col {{ display:flex; flex-direction:column; justify-content:center; gap:1.1rem; padding:0 .35rem; }}
    .ts-stat {{ display:flex; flex-direction:column; gap:.2rem; }}
    .ts-stat small {{ color:var(--ts-muted); font-size:.68rem; font-weight:700; text-transform:uppercase;
      letter-spacing:.05em; }}
    .ts-stat b {{ font-size:1.5rem; font-weight:850; letter-spacing:-.02em; }}
    .ts-stat.risk b {{ color:var(--ts-accent); }} .ts-stat.opportunity b {{ color:var(--ts-teal); }}
    /* Key KPI - reference design 1a: label on the left, figure and its YoY
       delta right-aligned on the same row, in a light 2-up card grid. */
    /* auto-FILL, not auto-fit: auto-fit collapses the empty tracks, so a
       single KPI stretched across the whole row as one enormous bar. auto-fill
       keeps the empty tracks, so one card is the same compact size as four. */
    .ts-kpi-row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:.75rem;
      margin-top:.65rem; }}
    .ts-kpi-card {{ display:flex; flex-direction:column; justify-content:space-between; gap:.5rem;
      min-height:104px; padding:.85rem 1rem;
      border:1px solid color-mix(in srgb,var(--ts-line) 55%,transparent);
      border-radius:9px; background:var(--ts-panel); transition:border-color .15s, box-shadow .15s; }}
    .ts-kpi-card:hover {{ border-color:color-mix(in srgb,var(--ts-accent) 45%,var(--ts-line));
      box-shadow:0 2px 8px color-mix(in srgb,var(--ts-accent) 14%,transparent); }}
    .ts-kpi-card > small {{ display:block; color:var(--ts-muted); font-size:.78rem; font-weight:500;
      text-transform:none; letter-spacing:0; margin-bottom:0; line-height:1.35; }}
    .ts-kpi-figure {{ flex:none; }}
    .ts-kpi-card b {{ display:block; font-size:1.32rem; font-weight:800;
      color:var(--ts-ink); letter-spacing:-.02em; white-space:nowrap; }}
    .ts-kpi-delta {{ display:block; margin-top:.15rem; font-size:.72rem; font-weight:650;
      color:var(--ts-muted); white-space:nowrap; }}
    /* Evidence & Sources - reference design 1a's outlined "Link" chip. */
    .ts-source-list {{ list-style:none; margin:0; padding:0; }}
    .ts-source-list li {{ display:flex; justify-content:space-between; align-items:center; gap:.6rem;
      padding:.55rem 0; border-bottom:1px solid color-mix(in srgb,var(--ts-line) 38%,transparent);
      font-size:.8rem; font-weight:500; color:var(--ts-muted); }}
    .ts-source-list li:last-child {{ border-bottom:0; }}
    .ts-source-list a {{ display:inline-flex; align-items:center; gap:.25rem; padding:.18rem .55rem;
      border:1px solid color-mix(in srgb,var(--ts-accent) 45%,var(--ts-line)); border-radius:5px;
      color:var(--ts-accent); text-decoration:none; font-weight:700; font-size:.68rem; white-space:nowrap; }}
    .ts-source-list a:hover {{ background:color-mix(in srgb,var(--ts-accent) 10%,transparent); }}
    .ts-section-grid {{ display:grid; grid-template-columns:1.05fr 1.1fr 1.35fr; gap:.7rem; margin-top:.65rem; }}
    /* Korean has no inter-word break opportunity by default, so a track that
       shrinks below its text's natural width wraps after *every syllable* -
       the "글자가 세로로 깨지는" report. keep-all restores word-boundary
       breaking; the minmax floors below stop tracks collapsing that far in
       the first place. Both are needed: keep-all alone would overflow. */
    .ts-card, .ts-card *, .ts-kpi-card, .ts-kpi-card * {{ word-break:keep-all; overflow-wrap:anywhere; }}
    /* Shown once at the top when half the purpose's slots found no evidence -
       that is a collection failure, not a layout one, and it reads differently
       from any single thin card. */
    .ts-under-evidenced {{ min-height:0; max-height:none; margin-top:.65rem;
      border-color:color-mix(in srgb,var(--ts-accent) 40%,var(--ts-line));
      background:color-mix(in srgb,var(--ts-accent) 6%,var(--ts-panel)); }}
    .ts-under-evidenced h3 {{ margin:0 0 .3rem; font-size:.92rem; }}
    .ts-under-evidenced p {{ margin:0; font-size:.8rem; color:var(--ts-muted); line-height:1.5; }}
    /* Deployment stamp - fixed bottom-right, deliberately quiet. */
    .ts-build-stamp {{ position:fixed; right:.85rem; bottom:.6rem; z-index:60;
      padding:.2rem .5rem; border-radius:5px; font-size:.66rem; font-weight:600;
      letter-spacing:.01em; color:var(--ts-muted); background:var(--ts-panel);
      border:1px solid color-mix(in srgb,var(--ts-line) 45%,transparent);
      opacity:.65; pointer-events:auto; }}
    .ts-build-stamp:hover {{ opacity:1; }}
    /* Cards - reference design 1a: light hairline border, small radius, and a
       plain-weight title underscored by a fading accent rule (no pill badge). */
    .ts-card {{ min-height:185px; max-height:210px; padding:1.05rem 1.25rem;
      border:1px solid color-mix(in srgb,var(--ts-line) 55%,transparent); border-radius:10px;
      background:var(--ts-panel); color:var(--ts-ink); overflow:hidden; }}
    .ts-card h3, .ts-card-inner h3 {{ display:block; position:relative; margin:0 0 1rem;
      padding:0 0 .45rem; border:0; border-radius:0; background:none; color:var(--ts-ink);
      font-size:.95rem; font-weight:700; letter-spacing:-.01em; }}
    .ts-card h3::after, .ts-card-inner h3::after {{ content:""; position:absolute; left:0; bottom:0;
      width:160px; max-width:70%; height:1.5px;
      background:linear-gradient(90deg,var(--ts-accent),color-mix(in srgb,var(--ts-accent) 0%,transparent)); }}
    /* Stage marker - the reference design groups its cards behind a vertical
       PROBLEM / CAUSE / IMPROVEMENT spine. Streamlit renders each element as
       its own block and can't wrap arbitrary containers in a custom grid, so
       the same grouping cue is carried by a slim horizontal band above the
       group instead of a rotated left rail. */
    .ts-rail-strip {{ display:flex; align-items:center; gap:.7rem; margin:1.1rem 0 .1rem;
      color:var(--ts-accent); font-size:.72rem; font-weight:800; letter-spacing:.16em; }}
    .ts-rail-strip span {{ flex:none; }}
    .ts-rail-strip::after {{ content:""; flex:1; height:2px; border-radius:2px;
      background:linear-gradient(90deg,var(--ts-accent),color-mix(in srgb,var(--ts-accent) 0%,transparent)); }}
    /* Sections the planner dropped for lack of evidence, with its reason -
       an absent section is information, not something to hide. */
    .ts-omitted {{ margin:.9rem 0 .2rem; padding:.7rem .95rem; border-radius:10px;
      border:1px dashed color-mix(in srgb,var(--ts-line) 70%,transparent);
      background:color-mix(in srgb,var(--ts-soft) 55%,transparent); }}
    .ts-omitted small {{ display:block; margin-bottom:.35rem; color:var(--ts-muted);
      font-size:.7rem; font-weight:700; letter-spacing:.03em; }}
    .ts-omitted ul {{ margin:0; padding-left:1.1rem; }}
    .ts-omitted li {{ font-size:.78rem; color:var(--ts-muted); line-height:1.6; }}
    .ts-omitted li b {{ color:var(--ts-ink); font-weight:700; margin-right:.4rem; }}
    /* Item comparison - several metrics sharing a unit at one point in time.
       Bar length is the real value over the group's largest. */
    .ts-compare {{ display:flex; flex-direction:column; gap:.45rem; margin-bottom:.6rem; }}
    .ts-compare > b {{ font-size:.8rem; color:var(--ts-muted); font-weight:700; }}
    .ts-compare-row {{ display:grid; grid-template-columns:minmax(90px,150px) minmax(0,1fr) 96px;
      align-items:center; gap:.6rem; font-size:.78rem; }}
    .ts-compare-row .label {{ color:var(--ts-ink); font-weight:600; }}
    .ts-compare-row .value {{ text-align:right; font-weight:700; color:var(--ts-ink); white-space:nowrap; }}
    .ts-compare-track {{ height:9px; border-radius:5px; background:var(--ts-soft); overflow:hidden; }}
    .ts-compare-fill {{ --pct:0%; width:var(--pct); height:100%; border-radius:5px;
      background:linear-gradient(90deg,var(--ts-accent),var(--ts-orange)); }}
    /* Cause -> effect -> response columns. No arrows between items: the data
       says which facts exist, not which cause produced which impact. */
    .ts-cause-map {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.7rem; }}
    .ts-cause-col {{ padding:.75rem .85rem; border-radius:10px; background:var(--ts-panel2);
      border:1px solid color-mix(in srgb,var(--ts-line) 45%,transparent); }}
    .ts-cause-col h4 {{ margin:0 0 .5rem; font-size:.8rem; font-weight:800; letter-spacing:.02em;
      color:var(--ts-accent); }}
    .ts-cause-col.impact h4 {{ color:var(--ts-orange); }}
    .ts-cause-col.action h4 {{ color:var(--ts-teal); }}
    .ts-cause-col ol {{ margin:0; padding-left:1.05rem; }}
    .ts-cause-col li {{ font-size:.78rem; line-height:1.5; margin:.3rem 0; color:var(--ts-ink); }}
    /* Metric chart - hand-drawn SVG in the reference's chart language
       (hairline gridlines, filled area under the primary series, ringed
       points, evidence-stated period labels) instead of Streamlit's default. */
    .ts-chart {{ display:flex; flex-direction:column; gap:.3rem; }}
    .ts-chart-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:.6rem; }}
    .ts-chart-head b {{ font-size:.9rem; font-weight:700; color:var(--ts-ink); }}
    .ts-chart-unit {{ font-size:.68rem; color:var(--ts-muted); }}
    .ts-chart-legend {{ display:flex; flex-wrap:wrap; gap:.75rem; }}
    .ts-chart-key {{ display:inline-flex; align-items:center; gap:.3rem; font-size:.68rem;
      font-weight:600; color:var(--ts-muted); }}
    .ts-chart-key i {{ width:9px; height:2.5px; border-radius:2px; }}
    .ts-chart-svg {{ display:block; width:100%; height:165px; overflow:visible; }}
    .ts-chart-axis {{ font-family:"Pretendard Variable",Pretendard,sans-serif; font-size:9px;
      fill:var(--ts-muted); }}
    .ts-card ul {{ margin:.4rem 0 0; padding-left:1.15rem; }} .ts-card li {{ margin:.55rem 0; line-height:1.4; }}
    .ts-empty {{ color:var(--ts-muted); font-size:.83rem; line-height:1.55; }}
    .ts-source-row {{ display:grid; grid-template-columns:110px 1fr 70px; gap:.5rem; padding:.58rem 0;
      border-bottom:1px solid color-mix(in srgb,var(--ts-line) 45%,transparent); font-size:.78rem; }}
    .ts-source-row b {{ color:var(--ts-accent); }}
    .ts-source-row .ts-dot {{ margin-right:.3rem; }}
    .ts-table-wrap {{ overflow-x:auto; }}
    .ts-table {{ width:100%; border-collapse:collapse; font-size:.78rem; }}
    .ts-table th {{ text-align:left; color:var(--ts-muted); font-weight:700; font-size:.7rem;
      text-transform:uppercase; letter-spacing:.03em; padding:.4rem .5rem; border-bottom:1px solid var(--ts-line); }}
    .ts-table td {{ padding:.5rem; border-bottom:1px solid color-mix(in srgb,var(--ts-line) 35%,transparent);
      white-space:nowrap; }}
    .ts-table tr:last-child td {{ border-bottom:0; }}
    .ts-dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:.4rem; }}
    .ts-dot.low {{ background:var(--ts-accent); }} .ts-dot.medium {{ background:var(--ts-orange); }}
    .ts-dot.high {{ background:var(--ts-teal); }}
    .ts-metric-groups {{ display:flex; gap:1.6rem; flex-wrap:wrap; margin-top:.3rem; }}
    .ts-metric-groups .ts-stat b {{ color:var(--ts-accent); }}
    .ts-metric-groups ul {{ margin:.35rem 0 0; padding-left:1.1rem; font-size:.82rem; color:var(--ts-ink); }}
    .ts-duo {{ display:grid; grid-template-columns:1fr 1fr; margin-top:.3rem; }}
    .ts-duo-cell {{ padding:.4rem .8rem; }} .ts-duo-cell:first-child {{ border-right:1px solid var(--ts-line); }}
    .ts-duo-cell h4 {{ margin:0 0 .35rem; font-size:.92rem; color:var(--ts-ink); }}
    .ts-duo-cell ul {{ margin:0; padding-left:1.1rem; font-size:.82rem; }}
    .ts-swot {{ display:grid; grid-template-columns:1fr 1fr; gap:.55rem; }}
    .ts-swot-cell {{ min-height:104px; padding:.75rem .85rem; border-radius:16px; }}
    .ts-swot-cell.positive {{ background:color-mix(in srgb,var(--ts-teal) 10%,var(--ts-panel));
      border:1px solid color-mix(in srgb,var(--ts-teal) 30%,var(--ts-line)); }}
    .ts-swot-cell.negative {{ background:color-mix(in srgb,var(--ts-accent) 10%,var(--ts-panel));
      border:1px solid color-mix(in srgb,var(--ts-accent) 30%,var(--ts-line)); }}
    .ts-swot-cell h4 {{ display:inline-block; margin:0 0 .5rem; padding:.22rem .75rem; border-radius:999px;
      color:#fff; font-size:.82rem; font-weight:800; letter-spacing:.01em; }}
    .ts-swot-cell.positive h4 {{ background:var(--ts-teal); }}
    .ts-swot-cell.negative h4 {{ background:var(--ts-accent); }}
    .ts-swot-cell p {{ margin:.28rem 0; font-size:.78rem; line-height:1.4; }}
    .ts-actions {{ margin-top:.65rem; padding:.65rem 1rem; border:1.5px solid var(--ts-line); border-radius:20px;
      background:var(--ts-panel); }}
    .ts-actions h3 {{ margin:0 0 .45rem; color:var(--ts-ink); }}
    .ts-actions-head {{ display:grid; grid-template-columns:42px minmax(250px,1.5fr) minmax(160px,1fr) 44px;
      gap:.75rem; padding:0 .3rem .3rem; color:var(--ts-muted); font-size:.66rem; font-weight:700;
      text-transform:uppercase; letter-spacing:.04em; }}
    .ts-actions-head span:last-child, .ts-actions-head span:nth-child(3) {{ text-align:right; }}
    .ts-action-row {{ display:grid; grid-template-columns:42px minmax(250px,1.5fr) minmax(160px,1fr) 44px;
      gap:.75rem; align-items:center; padding:.5rem .3rem; border-bottom:1px solid var(--ts-line); font-size:.88rem; }}
    .ts-action-row:last-child {{ border-bottom:0; }} .ts-action-row .num {{ font-size:1.1rem; color:var(--ts-muted); }}
    .ts-action-row .action {{ font-weight:800; }}
    /* Expected-impact cell: plain right-aligned text (reference design's
       "Expected Impact" column). The rank-derived progress bar that used to
       live here was removed - it encoded nothing but row order. */
    .ts-action-row .impact {{ text-align:right; font-size:.8rem; font-weight:500; color:var(--ts-muted); }}
    .ts-action-row .impact.ts-empty {{ font-size:.74rem; opacity:.7; }}
    .ts-evidence-link {{ display:grid; place-items:center; width:27px; height:27px; border-radius:50%;
      background:color-mix(in srgb,var(--ts-accent) 28%,var(--ts-panel)); color:var(--ts-accent); text-decoration:none;
      justify-self:end; }}
    .ts-footer-note {{ display:flex; gap:1rem; margin-top:.45rem; padding:.45rem .8rem; border-bottom:1px solid var(--ts-orange);
      font-size:.82rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    /* auto-fit with a real 260px floor: empty panels are now dropped rather
       than filled with an apology, so the survivors must widen to take the
       space. minmax(0,…) let a track shrink below its text's width, which is
       what made Korean wrap one syllable per line. */
    .ts-purpose-grid {{ grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }}
    .ts-compact-list {{ list-style:none; margin:0; padding:0; }}
    .ts-compact-list li {{ display:grid; grid-template-columns:30px minmax(0,1fr) 26px; gap:.45rem;
      align-items:start; margin:0; padding:.48rem 0; border-bottom:1px solid color-mix(in srgb,var(--ts-line) 38%,transparent);
      font-size:.8rem; line-height:1.3; }}
    .ts-compact-list li:last-child {{ border-bottom:0; }}
    .ts-item-index {{ color:var(--ts-accent); font-weight:800; }}
    .ts-inline-evidence {{ display:grid; place-items:center; width:22px; height:22px; border-radius:50%;
      color:white; background:color-mix(in srgb,var(--ts-accent) 75%,#6e2525); text-decoration:none; font-weight:900; }}
    .ts-purpose-card.timeline .ts-compact-list {{ position:relative; padding-left:.45rem; }}
    .ts-purpose-card.timeline .ts-compact-list li {{ border-left:2px solid var(--ts-accent); padding-left:.7rem; }}
    .ts-action-basis {{ color:var(--ts-muted); font-size:.76rem; }}
    .ts-footer-note b {{ color:var(--ts-orange); white-space:nowrap; }}
    .ts-timeline {{ position:relative; margin:.4rem 0 .2rem .5rem; padding-left:1.8rem; }}
    .ts-timeline::before {{ content:""; position:absolute; left:.48rem; top:.35rem; bottom:.4rem;
      width:2px; background:linear-gradient(var(--ts-accent),var(--ts-orange)); }}
    .ts-timeline-step {{ position:relative; margin:0 0 1rem; padding:.75rem 1rem; border:1px solid var(--ts-line);
      border-radius:14px; background:var(--ts-panel2); color:var(--ts-ink); }}
    .ts-timeline-step::before {{ content:""; position:absolute; left:-1.73rem; top:1rem; width:.72rem; height:.72rem;
      border:3px solid var(--ts-panel); border-radius:50%; background:var(--ts-accent); box-shadow:0 0 0 1px var(--ts-accent); }}
    .ts-timeline-step b {{ color:var(--ts-accent); margin-right:.55rem; }}
    .ts-collection-row {{ display:grid; grid-template-columns:28px 52px minmax(180px,1fr) auto;
      align-items:center; gap:10px; margin:7px 0; padding:11px 14px; border:1px solid var(--ts-line);
      border-radius:12px; background:var(--ts-panel); color:var(--ts-ink); }}
    .ts-collection-icon {{ display:grid; place-items:center; width:24px; height:24px; border-radius:50%;
      font-weight:800; color:var(--ts-muted); background:var(--ts-soft); }}
    .ts-collection-order {{ color:var(--ts-muted); font-size:.82rem; }}
    .ts-collection-state {{ color:var(--ts-muted); font-size:.88rem; text-align:right; }}
    .ts-collection-row.completed .ts-collection-icon {{ color:#087f5b; background:#dff8ee; }}
    .ts-collection-row.failed .ts-collection-icon {{ color:#c92a2a; background:#fff0f0; }}
    .ts-collection-row.running .ts-collection-icon {{ color:var(--ts-accent); background:var(--ts-panel2); }}
    .ts-side-nav {{ display:grid; gap:.5rem; margin:3rem -.4rem 0; }}
    .ts-nav {{ padding:.8rem 1rem; border-radius:999px; color:var(--ts-ink); font-weight:750; }}
    .ts-nav.active {{ background:var(--ts-panel); color:var(--ts-accent); }}
    .ts-recent {{ margin-top:12rem; color:var(--ts-muted); font-size:.78rem; }}
    .ts-recent-item {{ padding:.55rem .65rem; border-radius:8px; color:var(--ts-ink); }}
    .ts-recent-item.active {{ background:color-mix(in srgb,var(--ts-panel) 45%,transparent); color:var(--ts-accent); }}
    .ts-bar-list {{ display:grid; gap:.5rem; }}
    .ts-bar-row {{ display:grid; grid-template-columns:28px minmax(0,1fr) 110px; align-items:center; gap:.6rem;
      font-size:.85rem; }}
    .ts-bar-row .num {{ color:var(--ts-muted); font-weight:800; }}
    .ts-bar-row .label {{ color:var(--ts-ink); font-weight:700; }}
    .ts-bar-compare {{ margin-bottom:.7rem; }}
    .ts-bar-compare b {{ display:block; margin-bottom:.35rem; font-size:.82rem; color:var(--ts-ink); }}
    .ts-bar-compare-row {{ display:grid; grid-template-columns:80px minmax(0,1fr) 90px; align-items:center;
      gap:.5rem; font-size:.76rem; margin:.25rem 0; }}
    .ts-bar-compare-row .period {{ color:var(--ts-muted); }}
    .ts-bar-compare-row .value {{ text-align:right; font-weight:700; color:var(--ts-ink); }}
    .ts-bar-compare-track {{ height:8px; border-radius:6px; background:var(--ts-soft); overflow:hidden; }}
    .ts-bar-compare-fill {{ --pct:0%; width:var(--pct); height:100%; border-radius:6px;
      background:linear-gradient(90deg,var(--ts-accent),var(--ts-orange)); }}
    .ts-radar {{ display:flex; flex-direction:column; align-items:center; gap:.6rem; }}
    .ts-radar svg {{ width:100%; max-width:280px; height:auto; }}
    .ts-radar-legend {{ display:flex; flex-wrap:wrap; gap:.6rem .9rem; justify-content:center; }}
    .ts-radar-legend-item {{ display:flex; align-items:center; gap:.35rem; color:var(--ts-ink); font-size:.78rem;
      font-weight:700; }}
    .ts-radar-legend-item i {{ display:inline-block; width:.65rem; height:.65rem; border-radius:50%; }}
    @media(max-width:1050px) {{ .ts-section-grid{{grid-template-columns:1fr}} .ts-summary-grid{{grid-template-columns:1fr}}
      .ts-action-row{{grid-template-columns:40px 1fr}} .ts-action-row .impact,.ts-action-row .ts-evidence-link{{display:none}} }}
    @media(max-width:720px) {{ .block-container{{padding:1rem .8rem 2rem}} .ts-landing .ts-wordmark-text{{font-size:3.5rem}}
      .ts-context-line{{gap:.7rem;flex-wrap:wrap;margin-left:.3rem}} .ts-summary{{padding:1.2rem;border-radius:20px}} }}
    </style>
    """
