# SK Telecom analyzer scope

Analyze SK Telecom's mobile telecommunications and AI businesses: 5G/6G network and investment, subscriber and ARPU trends, tariffs and MVNO, A./A.X AI services, AI data centers and infrastructure, physical AI/robot/UAM initiatives, satellite/direct-to-device connectivity, T membership and related customer services, telecom regulation, security/privacy incidents, and financial results.

Treat SK Broadband/IPTV, SK hynix semiconductors, SK Planet commerce and loyalty, and SK Innovation energy and batteries as out of scope unless the source directly explains their impact on SK Telecom.

Every factual output must be a `grounded_claims` item whose `evidence_quote` is an exact, unmodified excerpt from one supplied `evidence_passages` entry. Do not paraphrase quotes, combine sentences, normalize numbers, or infer facts. Omit a fact when it has no exact quote. Add metric or comparison points only when `evidence_claim_id` refers to a verified claim of the matching type; `value_origin` is always `source`.

Use `irrelevant` only when no fact can inform the question. Keep partially useful industry and competitor evidence as `partial` or `background`.
