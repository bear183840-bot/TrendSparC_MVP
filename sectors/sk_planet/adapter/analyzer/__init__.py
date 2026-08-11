"""Evidence-grounded analyzer for SK Planet."""
from __future__ import annotations
import json, os
from pathlib import Path
from openai import OpenAI
from common.ai_client import openai_client_kwargs
from common.analyzer_quality import filter_points_by_verified_claim, split_content, split_evidence_passages, verify_claim_quotes
from common.content_quality_validator import COMPARISON_COMPLETENESS_INSTRUCTION, RELATIVE_METRIC_EXTRACTION_INSTRUCTION, SWOT_COMPLETENESS_INSTRUCTION, TABLE_COMPLETENESS_INSTRUCTION
from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from sources.openai_retry import call_with_truncation_retry

_API_KEY_ENV_VAR="TRENDSPARC_SK_PLANET_ANALYZER_API_KEY"; _BASE_URL_ENV_VAR="TRENDSPARC_SK_PLANET_ANALYZER_BASE_URL"; _MODEL="gpt-4o"; _STAGE="sectors.sk_planet.adapter.analyzer"
_ANALYSIS_MAX_TOKENS=4500; _ANALYSIS_MAX_TOKENS_ESCALATED=7000; _MAX_CLAIMS_PER_CALL=20; _MAX_METRIC_POINTS_PER_CALL=16; _MAX_COMPARISON_POINTS_PER_CALL=8
_SECTOR_ROOT=Path(__file__).resolve().parent.parent.parent; _PROJECT_ROOT=_SECTOR_ROOT.parent.parent
_ANALYZER_PROMPT_PATH=_PROJECT_ROOT/"prompts"/"analyzer_system_prompt.md"; _SECTOR_PROMPT_PATH=_SECTOR_ROOT/"prompts"/"analyzer_prompt.md"
_TYPES=["key_point","business_impact","risk","opportunity","strength","weakness","comparison","metric","factor","action","monitoring"]
_CLAIM={"type":"object","properties":{"claim_id":{"type":"string"},"claim_type":{"type":"string","enum":_TYPES},"claim":{"type":"string"},"evidence_passage_id":{"type":["string","null"]},"evidence_quote":{"type":"string"},"evidence_location":{"type":["string","null"]},"as_of_date":{"type":["string","null"]},"confidence":{"type":"string","enum":["low","medium","high"]}},"required":["claim_id","claim_type","claim","evidence_passage_id","evidence_quote","evidence_location","as_of_date","confidence"],"additionalProperties":False}
_METRIC={"type":"object","properties":{"label":{"type":"string"},"period":{"type":"string"},"value":{"type":"number"},"unit":{"type":["string","null"]},"subject":{"type":["string","null"]},"is_relative":{"type":"boolean"},"comparison_period":{"type":["string","null"]},"value_origin":{"type":"string","enum":["source"]},"evidence_claim_id":{"type":"string"}},"required":["label","period","value","unit","subject","is_relative","comparison_period","value_origin","evidence_claim_id"],"additionalProperties":False}
_COMPARISON={"type":"object","properties":{"entity":{"type":"string"},"criterion":{"type":"string"},"value":{"type":"string"},"level":{"type":["string","null"],"enum":["low","medium","high",None]},"evidence_claim_id":{"type":"string"}},"required":["entity","criterion","value","level","evidence_claim_id"],"additionalProperties":False}
_ANALYSIS_SCHEMA={"type":"object","properties":{"summary":{"type":"string"},"relevance_level":{"type":"string","enum":["direct","partial","background","irrelevant"]},"grounded_claims":{"type":"array","maxItems":_MAX_CLAIMS_PER_CALL,"items":_CLAIM},"metric_points":{"type":"array","maxItems":_MAX_METRIC_POINTS_PER_CALL,"items":_METRIC},"comparison_points":{"type":"array","maxItems":_MAX_COMPARISON_POINTS_PER_CALL,"items":_COMPARISON},"analysis_confidence":{"type":"string","enum":["low","medium","high"]}},"required":["summary","relevance_level","grounded_claims","metric_points","comparison_points","analysis_confidence"],"additionalProperties":False}
_REPAIR={"type":"object","properties":{"repairs":{"type":"array","items":{"type":"object","properties":{"claim_id":{"type":"string"},"evidence_passage_id":{"type":["string","null"]},"evidence_quote":{"type":["string","null"]}},"required":["claim_id","evidence_passage_id","evidence_quote"],"additionalProperties":False}}},"required":["repairs"],"additionalProperties":False}
def _load_system_prompt(): return "\n\n".join([_ANALYZER_PROMPT_PATH.read_text(encoding="utf-8"),_SECTOR_PROMPT_PATH.read_text(encoding="utf-8"),SWOT_COMPLETENESS_INSTRUCTION,COMPARISON_COMPLETENESS_INSTRUCTION,TABLE_COMPLETENESS_INSTRUCTION,RELATIVE_METRIC_EXTRACTION_INSTRUCTION])
def _repair(client,failed,passages):
 if not failed:return []
 try:r=client.chat.completions.create(model=_MODEL,max_tokens=800,temperature=0,messages=[{"role":"system","content":"Repair citations only. Never alter a claim; return an exact quote from a supplied passage or null."},{"role":"user","content":json.dumps({"claims":[{"claim_id":c["claim_id"],"claim":c["claim"]} for c in failed],"passages":passages},ensure_ascii=False)}],response_format={"type":"json_schema","json_schema":{"name":"sk_planet_quote_repair","schema":_REPAIR,"strict":True}}); repairs=json.loads(r.choices[0].message.content)["repairs"]
 except Exception:return []
 originals={c["claim_id"]:c for c in failed}; return [{**originals[x["claim_id"]],**x} for x in repairs if x.get("claim_id") in originals and x.get("evidence_quote")]
def _part(client,prompt,doc,question,content):
 passages=split_evidence_passages(content); user=json.dumps({"question":question,"document":{"title":doc.title,"url":doc.url,"evidence_passages":passages}},ensure_ascii=False)
 try:
  response,_=call_with_truncation_retry(lambda m:client.chat.completions.create(model=_MODEL,max_tokens=m,messages=[{"role":"system","content":prompt},{"role":"user","content":user}],response_format={"type":"json_schema","json_schema":{"name":"sk_planet_document_analysis","schema":_ANALYSIS_SCHEMA,"strict":True}}),[_ANALYSIS_MAX_TOKENS,_ANALYSIS_MAX_TOKENS_ESCALATED]); message=response.choices[0].message
  if message.refusal:raise PipelineStageError(stage=_STAGE,reason="analysis refused",detail=message.refusal)
  data=json.loads(message.content)
 except PipelineStageError:raise
 except Exception as exc:raise PipelineStageError(stage=_STAGE,reason=f"analysis API call failed for doc '{doc.doc_id}'",detail=str(exc)) from exc
 good,bad=verify_claim_quotes(data["grounded_claims"],passages,source_url=doc.url); fixed,_=verify_claim_quotes(_repair(client,bad,passages),passages,source_url=doc.url); claims=[*good,*fixed]; level=data["relevance_level"]; status="not_applicable" if level=="irrelevant" else ("insufficient_grounding" if not claims else ("partial_grounding" if len(claims)<len(data["grounded_claims"]) else "verified"))
 return DocumentAnalysis(doc_id=doc.doc_id,source_id=doc.source_id,source_title=doc.title,source_url=doc.url,reliability_tier=doc.reliability_tier,summary=data["summary"],relevant_to_question=level!="irrelevant",relevance_level=level,grounded_claims=claims,key_points=[c["claim"] for c in claims if c["claim_type"]=="key_point"],metric_points=filter_points_by_verified_claim(data["metric_points"],claims,claim_type="metric"),comparison_points=filter_points_by_verified_claim(data["comparison_points"],claims,claim_type="comparison"),evidence=[c["evidence_quote"] for c in claims],analysis_confidence=data["analysis_confidence"],analysis_validation_status=status,usable_for_synthesis=level!="irrelevant" and bool(claims))
def analyze(source_documents,question,information_needs=None,evidence_requirements=None):
 key=os.environ.get(_API_KEY_ENV_VAR)
 if not key:raise PipelineStageError(stage=_STAGE,reason=f"template_only: {_API_KEY_ENV_VAR} is not configured")
 client=OpenAI(api_key=key,**openai_client_kwargs(_BASE_URL_ENV_VAR)); prompt=_load_system_prompt(); out=[]
 for doc in source_documents:
  parts=[_part(client,prompt,doc,question,c) for c in split_content(doc.content or "")]
  if len(parts)==1:out.append(parts[0]);continue
  claims=[claim for part in parts for claim in part.grounded_claims]; ids={c.claim_id for c in claims}; out.append(DocumentAnalysis(doc_id=doc.doc_id,source_id=doc.source_id,source_title=doc.title,source_url=doc.url,reliability_tier=doc.reliability_tier,summary=" ".join(p.summary or "" for p in parts),relevant_to_question=any(p.relevant_to_question for p in parts),relevance_level=next((p.relevance_level for p in parts if p.relevance_level!="irrelevant"),"irrelevant"),grounded_claims=claims,key_points=[c.claim for c in claims if c.claim_type=="key_point"],metric_points=[x for p in parts for x in p.metric_points if x.evidence_claim_id in ids],comparison_points=[x for p in parts for x in p.comparison_points if x.evidence_claim_id in ids],evidence=[c.evidence_quote for c in claims],analysis_confidence="low" if any(p.analysis_confidence=="low" for p in parts) else "medium",analysis_validation_status="verified" if claims else "insufficient_grounding",usable_for_synthesis=bool(claims)))
 return out
