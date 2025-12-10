from openai import OpenAI
from dotenv import load_dotenv
import os
load_dotenv()

client = OpenAI(
    api_key=os.getenv("TEST_KEY"),
    base_url=os.getenv("TEST_URL")
)

resp = client.chat.completions.create(
    model=os.getenv("TEST_MODEL"),
    messages=[
        {"role": "user", "content": "你好，请自我介绍一下"}
    ],
)

print(resp.choices[0].message.content)