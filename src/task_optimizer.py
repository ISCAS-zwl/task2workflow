import logging
from typing import Dict, Any

from openai import OpenAI

from src.config import get_config

logger = logging.getLogger(__name__)


class TaskOptimizer:
    
    def __init__(self, model: str | None = None):
        self.config = get_config()
        self.model = model or self.config.planner_model
        self.client = OpenAI(
            api_key=self.config.planner_key,
            base_url=self.config.planner_url,
        )
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def _build_optimization_prompt(self, task: str) -> str:
        return f"""你是一个任务优化助手。用户提供了一个可能不够明确的任务描述，你需要补全缺失的关键信息，使其更加完整和可执行。

用户任务: {task}

请分析该任务，并补全以下可能缺失的信息：
1. **时间范围**: 如果任务涉及时间序列数据（如"过去X天"、"最近X个月"），但用户未明确指定，请根据常识补充合理的默认值
2. **输出格式**: 如果任务需要保存结果（如"保存为文件"），但未指定格式，请补充常见格式（Excel/CSV/JSON/图表等）
3. **数据范围**: 如果任务涉及数据获取但范围模糊，请明确数量或范围
4. **操作细节**: 如果任务包含"分析"、"处理"等模糊动词，请具体化操作步骤

补全规则:
- 只补充明显缺失且影响任务执行的信息
- 使用常见的默认值（如时间默认7天、文件格式默认Excel）
- 保持原任务的核心意图不变
- 如果原任务已经足够明确，直接返回原任务

直接输出优化后的任务描述，不要添加任何解释或前缀。"""
    
    def optimize(self, task: str) -> str:
        if not task or not task.strip():
            self.logger.warning("Empty task provided, skipping optimization")
            return task
        
        if not self.config.enable_task_optimization:
            self.logger.info("Task optimization disabled, using original task")
            return task
        
        try:
            prompt = self._build_optimization_prompt(task)
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a task optimization assistant. Output optimized task only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=500,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            
            optimized_task = resp.choices[0].message.content.strip() if resp.choices else ""
            
            if not optimized_task:
                self.logger.warning("LLM returned empty optimization result, using original task")
                return task
            
            if optimized_task == task:
                self.logger.info("Task already optimal, no changes needed")
            else:
                self.logger.info(f"Task optimized:\n  Original: {task}\n  Optimized: {optimized_task}")
            
            return optimized_task
            
        except Exception as e:
            self.logger.error(f"Task optimization failed: {e}, using original task")
            return task
