import json  
from openai import OpenAI

client = OpenAI(
    api_key="sk-nXwEiqnITEqgKKsPPYJMrnEca8oTb9vKrkc9IMnE1HlrTVjJ", # 从https://cloud.siliconflow.cn/account/ak获取
    base_url="http://api.cipsup.cn/v1"
)

response = client.chat.completions.create(
        model="Qwen3-32B-no-thinking",
        messages=[
            {"role": "system", "content": "You are a travel assistant."},
            {"role": "user", "content": "生成“南京周末旅行攻略 + 车票推荐”，并以json格式返回。"}
        ],
        response_format={"type": "json_object"}
    )

print(response.choices[0].message.content)