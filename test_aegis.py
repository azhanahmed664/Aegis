import time
from openai import OpenAI

# 1. Point the client to your local machine running Ollama
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama" 
)

print("🚀 Pinging the local Qwen 2.5 Coder model...")
start_time = time.time()

try:
    response = client.chat.completions.create(
        model="qwen2.5-coder:1.5b",
        messages=[
            {"role": "system", "content": "You are the core quantitative engine of a financial risk system. Keep your answers extremely concise."},
            {"role": "user", "content": "Define Value at Risk (VaR) in one short sentence."}
        ],
        temperature=0.1
    )
    
    end_time = time.time()
    
    print(f"\n✅ Success! Response generated in {round(end_time - start_time, 2)} seconds.")
    print("-" * 50)
    print(response.choices[0].message.content)
    print("-" * 50)
    
except Exception as e:
    print(f"\n❌ Connection failed: {e}\nMake sure the Ollama app is running in the background.")