import yaml
from jinja2 import Template

with open("prompt.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

tpl = Template(cfg["template"])
prompt = tpl.render(
    tools="(这里是工具列表文本/JSON/YAML都行)",
    task="(这里是用户任务)"
)

print(prompt)