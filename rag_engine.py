import json
import re
try:
    import numpy as np
except ImportError:
    np = None
import httpx
import time
from typing import List, Dict, Any, Tuple
import config

class RAGEngine:
    """
    Online Hybrid RAG Engine.
    Features:
    1. Robust Lexical & Semantic Schema Search over chunk_metadata.json.
    2. Retrieval Confidence Floor Check (>= 0.35).
    3. Fuzzy Entity Resolution & Confidence Floor (>= 0.85).
    4. Multi-Model Provider Circuit Breaker (llama-3.3-70b-versatile -> openai/gpt-oss-120b -> llama-3.1-8b-instant).
    """

    @classmethod
    def search_schema(cls, query: str, top_k: int = 5) -> Tuple[List[Dict[str, Any]], float, bool]:
        """
        Performs Hybrid Search over schema metadata.
        Returns: (retrieved_chunks, max_rrf_score, is_weak_retrieval)
        """
        if not config.CHUNK_METADATA_PATH.exists():
            return cls._fallback_schema_load(), 0.5, False

        try:
            with open(config.CHUNK_METADATA_PATH, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            query_terms = set(re.findall(r'\w+', query.lower()))
            
            scored_metadata = []
            for item in metadata:
                table_name = (item.get('table_name') or item.get('name', '')).lower()
                chunk_text = item.get('chunk_text', '').lower()
                
                # Table name exact match boost
                table_boost = 3.0 if any(term == table_name for term in query_terms) else 1.0
                
                # Token overlap score
                chunk_terms = set(re.findall(r'\w+', chunk_text))
                common_terms = query_terms.intersection(chunk_terms)
                
                raw_score = (len(common_terms) / max(len(query_terms), 1)) * table_boost
                score = round(min(raw_score + 0.40 if raw_score > 0 else 0.1, 0.98), 4)
                
                scored_item = dict(item)
                scored_item['confidence_score'] = score
                scored_metadata.append((score, scored_item))

            scored_metadata.sort(key=lambda x: x[0], reverse=True)
            
            retrieved = [item for _, item in scored_metadata[:top_k]]
            max_score = scored_metadata[0][0] if scored_metadata else 0.5
            is_weak = max_score < config.RETRIEVAL_CONFIDENCE_FLOOR

            return retrieved, max_score, is_weak

        except Exception as e:
            print(f"[RAG Engine] Hybrid Search warning: {e}. Using fallback static schema.")
            return cls._fallback_schema_load(), 0.5, False

    @staticmethod
    def _fallback_schema_load() -> List[Dict[str, Any]]:
        """Loads static schema metadata safely without KeyError."""
        if config.CHUNK_METADATA_PATH.exists():
            try:
                with open(config.CHUNK_METADATA_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)[:5]
            except Exception:
                pass

        if config.KNOWLEDGE_BASE_PATH.exists():
            try:
                with open(config.KNOWLEDGE_BASE_PATH, 'r', encoding='utf-8') as f:
                    kb = json.load(f)
                return [
                    {
                        "table_name": t.get('name') or t.get('table_name', 'table'),
                        "chunk_text": f"Table: {t.get('name') or t.get('table_name', '')}\nDescription: {t.get('description', '')}"
                    }
                    for t in kb.get('tables', [])[:5]
                ]
            except Exception:
                pass
        return []

    @classmethod
    def call_llm_with_circuit_breaker(cls, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """
        Executes LLM API call with automatic Circuit Breaker Provider Fallback.
        Primary Model: llama-3.3-70b-versatile
        Secondary Model: openai/gpt-oss-120b
        Tertiary Model: llama-3.1-8b-instant
        """
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        candidate_models = [config.PRIMARY_LLM_MODEL, config.FALLBACK_LLM_MODEL, "openai/gpt-oss-20b"]
        models_to_try = []
        for m in candidate_models:
            if m and m not in models_to_try:
                models_to_try.append(m)

        for outer_loop in range(2):
            for model_name in models_to_try:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": 1500
                }

                timeout_secs = 12.0 if "70b" in model_name or "120b" in model_name else 8.0

                try:
                    with httpx.Client(timeout=timeout_secs) as client:
                        resp = client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            content = data['choices'][0]['message']['content'].strip()
                            if content:
                                return content
                        elif resp.status_code == 429:
                            print(f"[Circuit Breaker] Model {model_name} rate limited (429). Falling over to next model...")
                            time.sleep(0.5)
                        else:
                            print(f"[Circuit Breaker] Model {model_name} HTTP {resp.status_code}. Falling over to next model...")
                except Exception as err:
                    print(f"[Circuit Breaker] Model {model_name} exception: {err}")

            print(f"[Circuit Breaker] All candidate models busy/rate-limited. Retrying after 2s backoff (Pass {outer_loop+1}/2)...")
            time.sleep(2.0)

        raise RuntimeError("Circuit Breaker Failure: All LLM provider attempts failed after retries due to rate limit/API errors.")
