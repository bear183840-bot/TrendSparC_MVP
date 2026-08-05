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
    .ts-context-line {{ display:flex; gap:2.2rem; align-items:center; margin:.25rem 1.4rem .5rem;
      color:var(--ts-ink); font-weight:750; }}
    .ts-context-line span small {{ color:var(--ts-muted); font-size:.68rem; margin-right:.7rem; font-weight:500; }}
    .ts-summary-grid {{ display:grid; grid-template-columns:minmax(0,1fr) 210px; gap:1.2rem; align-items:stretch; }}
    .ts-summary {{ padding:.8rem 1.45rem .9rem; border-radius:24px; background:var(--ts-accent); color:white; }}
    .ts-summary h2 {{ margin:0 0 .38rem; padding-bottom:.35rem; border-bottom:1px solid rgba(255,255,255,.5);
      color:white; font-size:1.25rem; }}
    .ts-summary p {{ margin:0; font-size:.94rem; line-height:1.38; font-weight:700; letter-spacing:-.02em;
      display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }}
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
    .ts-kpi-row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.7rem;
      margin-top:.65rem; }}
    .ts-kpi-card {{ padding:.75rem 1rem; border:1.5px solid var(--ts-line); border-radius:16px;
      background:var(--ts-panel); }}
    .ts-kpi-card small {{ display:block; color:var(--ts-muted); font-size:.7rem; font-weight:700;
      text-transform:uppercase; letter-spacing:.04em; margin-bottom:.3rem; }}
    .ts-kpi-card b {{ font-size:1.35rem; font-weight:850; color:var(--ts-ink); letter-spacing:-.02em; }}
    .ts-kpi-delta {{ display:block; margin-top:.25rem; font-size:.74rem; font-weight:700; color:var(--ts-muted); }}
    .ts-source-list {{ list-style:none; margin:0; padding:0; }}
    .ts-source-list li {{ display:flex; justify-content:space-between; gap:.6rem; padding:.5rem 0;
      border-bottom:1px solid color-mix(in srgb,var(--ts-line) 38%,transparent); font-size:.82rem; }}
    .ts-source-list li:last-child {{ border-bottom:0; }}
    .ts-source-list a {{ color:var(--ts-accent); text-decoration:none; font-weight:700; white-space:nowrap; }}
    .ts-section-grid {{ display:grid; grid-template-columns:1.05fr 1.1fr 1.35fr; gap:.7rem; margin-top:.65rem; }}
    .ts-card {{ min-height:185px; max-height:210px; padding:.75rem 1rem; border:1.5px solid var(--ts-line); border-radius:20px;
      background:var(--ts-panel); color:var(--ts-ink); overflow:hidden; }}
    .ts-card h3, .ts-card-inner h3 {{ display:inline-block; margin:0 0 .55rem; padding:.32rem 1.05rem;
      border:0; border-radius:999px; background:var(--ts-accent); color:#fff; font-size:.92rem; font-weight:800;
      letter-spacing:-.01em; }}
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
    .ts-action-row > span:has(.ts-impact) {{ text-align:right; }}
    .ts-action-row > span:has(.ts-impact) small {{ display:block; margin-bottom:.3rem; color:var(--ts-muted);
      font-size:.72rem; }}
    .ts-impact {{ --impact:60%; height:6px; border-radius:8px;
      background:linear-gradient(90deg,var(--ts-accent) 0 var(--impact),
      color-mix(in srgb,var(--ts-accent) 22%,transparent) var(--impact)); }}
    .ts-evidence-link {{ display:grid; place-items:center; width:27px; height:27px; border-radius:50%;
      background:color-mix(in srgb,var(--ts-accent) 28%,var(--ts-panel)); color:var(--ts-accent); text-decoration:none;
      justify-self:end; }}
    .ts-footer-note {{ display:flex; gap:1rem; margin-top:.45rem; padding:.45rem .8rem; border-bottom:1px solid var(--ts-orange);
      font-size:.82rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .ts-purpose-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
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
      .ts-action-row{{grid-template-columns:40px 1fr}} .ts-action-row .ts-impact,.ts-action-row .ts-evidence-link{{display:none}} }}
    @media(max-width:720px) {{ .block-container{{padding:1rem .8rem 2rem}} .ts-landing .ts-wordmark-text{{font-size:3.5rem}}
      .ts-context-line{{gap:.7rem;flex-wrap:wrap;margin-left:.3rem}} .ts-summary{{padding:1.2rem;border-radius:20px}} }}
    </style>
    """
