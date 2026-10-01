import feedparser
from openai import OpenAI
import time

class MacroHarvester:
    def __init__(self):
        # Institutional NLP Filter (Zero-Token Processing)
        self.keywords = ['CPI', 'PPI', 'FED', 'POWELL', 'RATE', 'INFLATION', 'WAR', 'SEC', 'LIQUIDATION', 'ETF', 'JOB', 'NFP']
        
        # Reliable Institutional Feeds
        self.feeds = {
            'Macro': 'https://www.forexlive.com/feed/news',
            'Crypto': 'https://cointelegraph.com/rss'
        }
        
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"
        )

    def scrape_and_filter(self) -> list:
        print("🌍 Scanning Global RSS Feeds (0 Tokens)...")
        critical_events = []
        
        for category, url in self.feeds.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:30]: # Scan the 30 most recent headlines per feed
                    title = entry.title.upper()
                    # Rule-based filter: Keep only if it contains a critical macroeconomic keyword
                    if any(kw in title for kw in self.keywords):
                        critical_events.append(f"[{category}] {entry.title}")
            except Exception as e:
                print(f"Failed to parse {category}: {e}")
                
        return critical_events

    def generate_macro_briefing(self) -> str:
        events = self.scrape_and_filter()
        
        if not events:
            return "No severe macro events detected in the current cycle."
            
        print(f"🚨 Detected {len(events)} High-Impact Events. Passing to Qwen AI...")
        
        # Join events into a highly condensed payload (Max 5 events to save tokens)
        payload = "\n".join(events[:5]) 
        
        system_prompt = (
            "You are a Bloomberg Terminal macro analyst. "
            "Review the provided high-impact headlines and write a highly concise, 3-sentence "
            "executive summary of the current macroeconomic environment and its likely impact on Crypto and Forex volatility. "
            "Do not include conversational filler text."
        )
        
        start_time = time.time()
        try:
            response = self.client.chat.completions.create(
                model="qwen2.5-coder:1.5b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Latest Critical Headlines:\n{payload}"}
                ],
                temperature=0.2,
                max_tokens=150
            )
            elapsed = round(time.time() - start_time, 2)
            print(f"⚡ Synthesis completed in {elapsed}s.\n")
            return response.choices[0].message.content
        except Exception as e:
            return f"LLM Connection Error: {e}"

if __name__ == "__main__":
    harvester = MacroHarvester()
    briefing = harvester.generate_macro_briefing()
    
    print("----- MACRO VOLATILITY BRIEFING -----")
    print(briefing)
    print("-------------------------------------")