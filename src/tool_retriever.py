import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openai import OpenAI

from src.config import get_config

logger = logging.getLogger(__name__)


def _split_identifier(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return text


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def _extract_schema_fields(schema: Any) -> Tuple[List[str], List[str]]:
    required_keys: List[str] = []
    optional_keys: List[str] = []

    if not isinstance(schema, dict):
        return required_keys, optional_keys

    properties = schema.get("properties")
    if isinstance(properties, dict):
        optional_keys.extend([str(key) for key in properties.keys()])

    required = schema.get("required")
    if isinstance(required, list):
        required_keys.extend([str(item) for item in required])

    if required_keys:
        required_set = set(required_keys)
        optional_keys = [key for key in optional_keys if key not in required_set]

    return required_keys, optional_keys


@dataclass
class ToolDoc:
    name: str
    description: str
    required_keys: List[str]
    optional_keys: List[str]
    raw: Dict[str, Any]


class BM25FieldIndex:
    def __init__(self, docs_tokens: List[Counter], k1: float, b: float):
        self.docs_tokens = docs_tokens
        self.k1 = k1
        self.b = b
        self.doc_len = [sum(counter.values()) for counter in docs_tokens]
        self.avgdl = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.df = Counter()
        for counter in docs_tokens:
            for term in counter.keys():
                self.df[term] += 1

    def score(self, query_tokens: Counter, doc_idx: int) -> float:
        if self.avgdl == 0.0:
            return 0.0
        doc_counter = self.docs_tokens[doc_idx]
        dl = self.doc_len[doc_idx]
        score = 0.0
        for term, qf in query_tokens.items():
            df = self.df.get(term, 0)
            if df == 0:
                continue
            tf = doc_counter.get(term, 0)
            if tf == 0:
                continue
            idf = math.log(1 + (len(self.docs_tokens) - df + 0.5) / (df + 0.5))
            denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf * (tf * (self.k1 + 1) / denom) * qf
        return score


class SemanticRetriever:
    def __init__(self, tools_data: Dict[str, Any]):
        self.config = get_config()
        self.tools_data = tools_data or {}
        self.docs = self._build_docs(self.tools_data)
        self.client: Optional[OpenAI] = None
        self.tool_embeddings: Optional[List[List[float]]] = None
        
        if self.config.embedding_url and self.config.embedding_key:
            self.client = OpenAI(
                api_key=self.config.embedding_key,
                base_url=self.config.embedding_url,
                timeout=self.config.embedding_timeout,
            )
            self._precompute_embeddings()
        else:
            logger.warning("Embedding API not configured, semantic retrieval disabled")
    
    @staticmethod
    def _build_docs(tools: Dict[str, Any]) -> List[ToolDoc]:
        docs: List[ToolDoc] = []
        for name, meta in tools.items():
            description = (meta or {}).get("description") or ""
            schema = (meta or {}).get("input_schema") or {}
            required_keys, optional_keys = _extract_schema_fields(schema)
            docs.append(
                ToolDoc(
                    name=str(name),
                    description=str(description),
                    required_keys=required_keys,
                    optional_keys=optional_keys,
                    raw=meta or {},
                )
            )
        return docs
    
    def _build_tool_text(self, doc: ToolDoc) -> str:
        parts = [f"Tool: {doc.name}"]
        if doc.description:
            parts.append(f"Description: {doc.description}")
        if doc.required_keys:
            parts.append(f"Required params: {', '.join(doc.required_keys)}")
        if doc.optional_keys:
            parts.append(f"Optional params: {', '.join(doc.optional_keys)}")
        return " | ".join(parts)
    
    def _get_embedding(self, text: str) -> Optional[List[float]]:
        if not self.client or not self.config.embedding_model:
            return None
        try:
            resp = self.client.embeddings.create(
                input=text,
                model=self.config.embedding_model,
            )
            return resp.data[0].embedding
        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            return None
    
    def _is_cache_valid(self, cache_path: Path, tools_path: Path) -> bool:
        if not cache_path.exists():
            return False
        if not tools_path.exists():
            return True
        try:
            cache_mtime = cache_path.stat().st_mtime
            tools_mtime = tools_path.stat().st_mtime
            return cache_mtime >= tools_mtime
        except Exception as e:
            logger.warning(f"Failed to check cache validity: {e}")
            return False
    
    def _load_cache(self, cache_path: Path) -> bool:
        if not cache_path.exists():
            return False
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            
            cached_tools = data.get("tools", [])
            embeddings = data.get("embeddings", [])
            
            if len(cached_tools) != len(self.docs):
                logger.info("Cache invalid: tool count mismatch")
                return False
            
            current_tool_names = [doc.name for doc in self.docs]
            if cached_tools != current_tool_names:
                logger.info("Cache invalid: tool names mismatch")
                return False
            
            if len(embeddings) != len(self.docs):
                logger.info("Cache invalid: embeddings count mismatch")
                return False
            
            self.tool_embeddings = embeddings
            logger.info(f"Loaded {len(embeddings)} embeddings from cache")
            return True
        except Exception as e:
            logger.warning(f"Failed to load embeddings cache: {e}")
            return False
    
    def _save_cache(self, cache_path: Path):
        if not self.tool_embeddings:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "tools": [doc.name for doc in self.docs],
                "embeddings": self.tool_embeddings,
            }
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            logger.info(f"Saved embeddings cache to {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to save embeddings cache: {e}")
    
    def _precompute_embeddings(self):
        cache_path = self.config.tool_embeddings_cache_path
        tools_path = self.config.tools_generated_path
        
        if self._is_cache_valid(cache_path, tools_path):
            if self._load_cache(cache_path):
                return
        
        logger.info(f"Computing embeddings for {len(self.docs)} tools...")
        embeddings = []
        for doc in self.docs:
            text = self._build_tool_text(doc)
            emb = self._get_embedding(text)
            if emb:
                embeddings.append(emb)
            else:
                embeddings.append([0.0] * 1536)
        self.tool_embeddings = embeddings
        logger.info("Embedding computation complete")
        
        self._save_cache(cache_path)
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)
    
    def retrieve(self, task: str, top_k: int = 20) -> List[Tuple[str, float]]:
        if not self.client or not self.tool_embeddings:
            logger.warning("Semantic retrieval not available, returning empty results")
            return []
        
        query_emb = self._get_embedding(task)
        if not query_emb:
            return []
        
        scores = []
        for idx, tool_emb in enumerate(self.tool_embeddings):
            sim = self._cosine_similarity(query_emb, tool_emb)
            scores.append((idx, sim))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(self.docs[idx].name, score) for idx, score in scores[:top_k]]
    
    def retrieve_subset(self, task: str, top_k: int = 20) -> Optional[Dict[str, Any]]:
        ranked = self.retrieve(task, top_k=top_k)
        if not ranked:
            return None
        result = {name: self.tools_data[name] for name, _score in ranked}

        # 添加固定工具
        pinned_tools = self.config.pinned_tools
        for tool_name in pinned_tools:
            if tool_name in self.tools_data and tool_name not in result:
                result[tool_name] = self.tools_data[tool_name]
                logger.info(f"Added pinned tool: {tool_name}")

        return result


class ToolRetriever:
    def __init__(
        self,
        tools_data: Dict[str, Any],
        field_weights: Optional[Dict[str, float]] = None,
        k1: float = 1.2,
        b: float = 0.75,
    ):
        self.config = get_config()
        self.tools_data = tools_data or {}
        self.field_weights = field_weights or {
            "name": 3.0,
            "desc": 2.0,
            "required": 1.5,
            "optional": 1.0,
        }
        self.docs = self._build_docs(self.tools_data)
        
        if self.config.retriever_mode == "semantic":
            self.semantic_retriever = SemanticRetriever(tools_data)
            self.index = None
        else:
            self.semantic_retriever = None
            self.index = self._build_index(self.docs, k1=k1, b=b)

    @staticmethod
    def _build_docs(tools: Dict[str, Any]) -> List[ToolDoc]:
        docs: List[ToolDoc] = []
        for name, meta in tools.items():
            description = (meta or {}).get("description") or ""
            schema = (meta or {}).get("input_schema") or {}
            required_keys, optional_keys = _extract_schema_fields(schema)
            docs.append(
                ToolDoc(
                    name=str(name),
                    description=str(description),
                    required_keys=required_keys,
                    optional_keys=optional_keys,
                    raw=meta or {},
                )
            )
        return docs

    def _build_index(self, docs: List[ToolDoc], k1: float, b: float) -> Dict[str, BM25FieldIndex]:
        field_tokens: Dict[str, List[Counter]] = defaultdict(list)
        for doc in docs:
            name_text = f"{doc.name} {_split_identifier(doc.name)}"
            desc_text = doc.description
            required_text = " ".join(doc.required_keys)
            optional_text = " ".join(doc.optional_keys)
            field_tokens["name"].append(Counter(_tokenize(name_text)))
            field_tokens["desc"].append(Counter(_tokenize(desc_text)))
            field_tokens["required"].append(Counter(_tokenize(required_text)))
            field_tokens["optional"].append(Counter(_tokenize(optional_text)))
        return {
            field: BM25FieldIndex(tokens, k1=k1, b=b)
            for field, tokens in field_tokens.items()
        }

    def retrieve(self, task: str, top_k: int = 20) -> List[Tuple[str, float]]:
        if self.semantic_retriever:
            return self.semantic_retriever.retrieve(task, top_k=top_k)
        
        tokens = _tokenize(task)
        if not tokens:
            return []
        query_tokens = Counter(tokens)
        results: List[Tuple[int, float]] = []
        for idx, _doc in enumerate(self.docs):
            score = 0.0
            for field, weight in self.field_weights.items():
                field_index = self.index.get(field)
                if not field_index:
                    continue
                score += weight * field_index.score(query_tokens, idx)
            if score > 0:
                results.append((idx, score))
        results.sort(key=lambda item: item[1], reverse=True)
        output: List[Tuple[str, float]] = []
        for idx, score in results[:top_k]:
            output.append((self.docs[idx].name, score))
        return output

    def retrieve_subset(self, task: str, top_k: int = 20) -> Optional[Dict[str, Any]]:
        if self.semantic_retriever:
            result = self.semantic_retriever.retrieve_subset(task, top_k=top_k)
        else:
            ranked = self.retrieve(task, top_k=top_k)
            if not ranked:
                result = None
            else:
                result = {name: self.tools_data[name] for name, _score in ranked}

        if result is None:
            result = {}

        # 添加固定工具
        pinned_tools = self.config.pinned_tools
        for tool_name in pinned_tools:
            if tool_name in self.tools_data and tool_name not in result:
                result[tool_name] = self.tools_data[tool_name]
                logger.info(f"Added pinned tool: {tool_name}")

        return result if result else None
