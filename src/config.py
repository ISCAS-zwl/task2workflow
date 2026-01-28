import os
from pathlib import Path
from typing import Optional


class Config:
    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        
        self.project_root = project_root
        self.prompt_dir = project_root / "prompt"
        self.tools_dir = project_root / "tools"
        self.plan_prompt_path = self.prompt_dir / "plan_prompt.txt"
        self.plan_stage1_prompt_path = self.prompt_dir / "plan_prompt_stage1.txt"
        self.plan_stage2_prompt_path = self.prompt_dir / "plan_prompt_stage2.txt"
        self.tools_generated_path = self.tools_dir / "generated_tools.json"
        self.tool_embeddings_cache_path = self.tools_dir / "tool_embeddings.json"
        self.planner_key = os.getenv("PLANNER_KEY")
        self.planner_url = os.getenv("PLANNER_URL")
        self.planner_model = os.getenv("PLANNER_MODEL", "gpt-4o")
        self.guard_key = os.getenv("GUARD_KEY")
        self.guard_url = os.getenv("GUARD_URL")
        self.guard_model = os.getenv("GUARD_MODEL")
        self.guard_timeout = int(os.getenv("GUARD_TIMEOUT", "60"))
        self.planner_timeout = int(os.getenv("PLANNER_TIMEOUT", "60"))
        
        self.embedding_key = os.getenv("EMBEDDING_KEY")
        self.embedding_url = os.getenv("EMBEDDING_URL")
        self.embedding_model = os.getenv("EMBEDDING_MODEL")
        self.embedding_timeout = int(os.getenv("EMBEDDING_TIMEOUT", "30"))
        self.retriever_mode = os.getenv("RETRIEVER_MODE", "bm25")
        
        self.enable_task_optimization = os.getenv("ENABLE_TASK_OPTIMIZATION", "true").lower() in ("true", "1", "yes")
        
        self.max_fix_attempts = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
        self.tool_retriever_top_k = int(os.getenv("TOOL_RETRIEVER_TOP_K", "25"))
        self.tool_retriever_expand_k = int(os.getenv("TOOL_RETRIEVER_EXPAND_K", "15"))
        self.log_truncate_length = int(os.getenv("LOG_TRUNCATE_LENGTH", "500"))
        self.fix_prompt_truncate_length = int(os.getenv("FIX_PROMPT_TRUNCATE_LENGTH", "1500"))

        # 固定工具列表：这些工具总是会被包含在检索结果中
        pinned_tools_str = os.getenv("PINNED_TOOLS", "tavily-search")
        self.pinned_tools = [t.strip() for t in pinned_tools_str.split(",") if t.strip()]


_default_config: Optional[Config] = None


def get_config() -> Config:
    global _default_config
    if _default_config is None:
        _default_config = Config()
    return _default_config


def set_config(config: Config):
    global _default_config
    _default_config = config
