## Use FastAPI
- 🐍 Python-based — ideal if you're already using Python/AI/ML
- ⚡ Fast — asynchronous support and high performance
- 📋 Automatic API documentation — Swagger/OpenAPI generated automatically
- 🔐 Easy to implement authentication/authorization
- 🧠 Excellent for AI/ML backends
- 🗄️ Works well with PostgreSQL/Supabase
- 🔌 Easy to integrate external APIs

```
React Native + Expo
        │
        │ HTTPS / REST API
        ▼
     FastAPI
        │
   ┌────┴─────┐
   ▼          ▼
Supabase    External APIs
(Postgres)  (OpenRouter,
            CoinGecko, Resend...)
```


```
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/price")
def get_price():
    return {
        "bitcoin": 105000,
        "currency": "USD"
    }
```

<br>
<br>

## xAI Search

Two different search tools in the xAI API.
<br>

**Web Search**: Grok searches the general internet in real time.
```
FastAPI
   ↓
xAI API
   ↓
Grok
   ↓
web_search
   ↓
Internet
```
You enable it with:
```
tools=[
    {
        "type": "web_search"
    }
]
```

**X Search**: This is specifically for X/Twitter posts, users and threads.

```
tools=[
    {
        "type": "x_search"
    }
]
```

For your crypto application
```
                 ┌─────────────────┐
                 │   Your FastAPI   │
                 │     Backend      │
                 └────────┬────────┘
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
      CoinGecko       OpenRouter          xAI
      market data     multiple LLMs     Grok
                                          │
                                   ┌──────┴──────┐
                                   ▼             ▼
                              Web Search     X Search
                              news/web       crypto sentiment

```
So you could ask Grok something like:

"Analyze the current Bitcoin situation. Search the web for the latest relevant news and search X for recent sentiment and important posts. Return the result in this JSON structure..."

And store the structured result in Supabase alongside the analyses from the OpenRouter models.