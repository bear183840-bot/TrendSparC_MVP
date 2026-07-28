# sk_hynix source registry

`sources.json` has 5 registered sources, each read by `core/source_planner`
into a `PlannedSource` — only fields already present in the entry below are
carried over, so nothing here invents a reliability tier for an
unregistered source.

| Name | Type | Collection method | Frequency |
|---|---|---|---|
| SK하이닉스 뉴스룸 | official_newsroom | rss, crawling | daily |
| 삼성전자DS 뉴스룸 | official_newsroom | rss, crawling | daily |
| 전자신문(반도체) | news_media | rss | daily |
| TrendForce Press Center | market_research | rss, crawling | daily |
| BIS (미국 상무부 산업안보국) Newsroom | government_newsroom | crawling | new_filings_only |

Each entry's `reliability_reason` is documented directly in `sources.json`.
Do not assign an arbitrary reliability tier to a source that hasn't been
registered here first — adding a new source means adding it to
`sources.json`, not inferring one at analysis time.
