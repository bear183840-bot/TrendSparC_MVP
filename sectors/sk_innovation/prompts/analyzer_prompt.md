# SK Innovation analyzer scope

Analyze only SK Innovation group businesses and the document's direct market context:

- SK On batteries: capacity, production, orders, joint ventures, customers, materials, and technology.
- SK Energy refining and oil business: refining margins, supply/demand, inventories, and results.
- SK geo centric petrochemicals and plastic recycling.
- SK Enmove lubricants and related mobility-energy businesses.
- SK E&S integration: LNG, power, renewable energy, hydrogen, and carbon-reduction business.
- ESG, resource development, financial results, investments, and risks relevant to these businesses.

Treat as out of scope unless the document directly connects them to SK Innovation's businesses: SK hynix/HBM semiconductors, SK Telecom mobile or AI services, SK Broadband/IPTV, and SK Planet commerce or loyalty services.

For every factual output, create a `grounded_claims` item. Its `evidence_quote` must be a verbatim excerpt from one supplied `evidence_passages` entry; do not paraphrase, normalize numbers, combine sentences, or infer missing facts. Use the matching passage ID. If no exact quote supports a fact, omit the fact.

Use `claim_type` to classify factual key points, business impacts, risks, opportunities, strengths, weaknesses, metrics, comparisons, factors, source-stated actions, and monitoring indicators. Add `metric_points` and `comparison_points` only when their `evidence_claim_id` refers to a verified claim of the corresponding type. A metric's `value_origin` is always `source`.

Mark a document `irrelevant` only when it contains no fact that can inform the question. A partial but useful source is `partial` or `background`.
