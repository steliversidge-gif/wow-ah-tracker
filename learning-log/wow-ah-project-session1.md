# WoW Auction House Tracker — Session 1 Plan

## The Goal

Build your own auction house pricing tool that gives you an edge TSM can't — personalised to your server, your markets, and your playstyle. Along the way, learn Python, APIs, databases, and eventually web development.

---

## What You're Building (Big Picture)

| Phase | What | Skills Learned |
|-------|------|----------------|
| **1** | Pull live AH data from Blizzard's API | Python, APIs, OAuth2, JSON |
| **2** | Store snapshots in a database over time | SQL (from code), database design, scheduling |
| **3** | Analyse pricing trends & crafting margins | Pandas, data modelling (your wheelhouse) |
| **4** | Build a web dashboard to surface opportunities | HTML/CSS/JS or a Python framework like Streamlit |
| **5+** | Alerts, profit tracking, predictive pricing | Whatever interests you at that point |

You don't need to plan beyond Phase 1 right now. Each phase naturally leads to the next.

---

## Session 1: "Pull Auction House Data into Python"

**Target duration:** 3–4 hours in one sitting
**What you'll have at the end:** A Python script that authenticates with Blizzard's API and prints live auction house data for your realm.

---

### Step 0 — Setup (~30 mins)

Install these if you don't have them:

1. **Python 3.x** — download from [python.org](https://python.org). On Windows, tick **"Add to PATH"** during install. This trips everyone up — don't skip it.
2. **VS Code** — free from [code.visualstudio.com](https://code.visualstudio.com). Install the **Python extension** from the Extensions tab once it's open.
3. **A terminal** — VS Code has one built in. Open it with `Ctrl + backtick`.

**Verify it works:** In the terminal, type:

```
python --version
```

If it prints a version number (e.g. `Python 3.12.x`), you're good. If not, restart VS Code or check PATH settings.

Then install the library you'll need:

```
pip install requests
```

---

### Step 1 — Get Your Blizzard API Credentials (~15 mins)

1. Go to [develop.battle.net](https://develop.battle.net) and log in with your Battle.net account.
2. Go to **API Access** and create a new client/application.
   - Give it any name (e.g. "AH Tracker").
   - Set the redirect URL to `http://localhost` — you won't actually use it, but the form requires one.
3. You'll get a **Client ID** and **Client Secret**. Copy both somewhere safe.

**What this is:** Unlike simpler APIs that give you a static key, Blizzard uses **OAuth2**. Your client ID and secret are like a username and password that your script uses to request a temporary access token. That token is what actually lets you make API calls. This is the standard for most modern APIs (Google, Spotify, etc.) so learning it now is valuable.

---

### Step 2 — Authenticate and Get an Access Token (~30 mins)

Create a file called `ah_tracker.py`. **Type this out manually** — the point is to feel every line and notice what you don't understand.

```python
import requests

# Your credentials from Step 1
CLIENT_ID = "your-client-id"
CLIENT_SECRET = "your-client-secret"

# Step 1: Get an access token
token_url = "https://oauth.battle.net/token"
token_response = requests.post(
    token_url,
    data={"grant_type": "client_credentials"},
    auth=(CLIENT_ID, CLIENT_SECRET)
)

print("Status:", token_response.status_code)

token_data = token_response.json()
access_token = token_data["access_token"]

print("Token:", access_token)
```

Run it: `python ah_tracker.py`

If you see `Status: 200` and a long string of characters — you've just authenticated with OAuth2. That's a genuine skill.

**Pause here and understand what happened:**

- `requests.post()` — you're sending data TO a server (POST), not just asking for data (GET). Why does authentication use POST?
- `auth=(CLIENT_ID, CLIENT_SECRET)` — this sends your credentials using HTTP Basic Auth. What does that mean?
- `grant_type=client_credentials` — this tells Blizzard "I'm an application, not a user logging in." OAuth2 has several flows; this is the simplest.
- The response gives you a token that expires (usually 24 hours). Your script will need to request a new one each time.

Use Claude to explain any of these concepts. The right prompt is something like: *"Explain OAuth2 client_credentials flow to me like I understand APIs at a basic level but have never used authentication before."*

---

### Step 3 — Pull Auction House Data (~45 mins)

Now add to your script:

```python
# Step 2: Get auction house data
# Replace these with your realm and region
realm_slug = "draenor"  # lowercase, hyphens for spaces
namespace = "dynamic-eu"  # dynamic-eu or dynamic-us
locale = "en_GB"

ah_url = f"https://eu.api.blizzard.com/data/wow/connected-realm/1929/auctions"
# Note: 1929 is Draenor EU's connected realm ID — you'll need to find yours

headers = {"Authorization": f"Bearer {access_token}"}
params = {"namespace": namespace, "locale": locale}

ah_response = requests.get(ah_url, headers=headers, params=params)
print("AH Status:", ah_response.status_code)

auctions = ah_response.json().get("auctions", [])
print(f"Total listings: {len(auctions)}")

# Look at the first auction
if auctions:
    print("\nFirst listing:")
    print(auctions[0])
```

**Finding your connected realm ID:** This is your first "read the docs" exercise. Go to the [Blizzard API docs](https://develop.battle.net/documentation/world-of-warcraft/game-data-apis) and find the **Connected Realm Index** endpoint. Call it first to find the ID for your realm. Resist asking Claude for the number — finding it yourself is the skill.

**What you'll see:** Each auction is a JSON object with fields like `item.id`, `buyout` (in copper), `quantity`, and `time_left`. The buyout is in copper, so divide by 10,000 to get gold.

---

### Step 4 — Make It Useful (~60 mins)

Pick ONE of these to try. Don't try all of them — depth beats breadth right now.

**Option A: "What's the cheapest listing for a specific item?"**

- Pick an item you trade (e.g. Shadowflame Essence, a common crafting mat).
- Filter the auctions list for that item ID.
- Sort by buyout price and print the cheapest listings.
- You'll need to look up item IDs — Blizzard's Item API or wowhead.com both work.

**Option B: "What are the most listed items right now?"**

- Count how many listings exist for each item ID.
- Sort by count and print the top 20.
- This tells you what markets are most active on your server.

**Option C: "What items have the widest price spread?"**

- For each item with multiple listings, find the min and max buyout.
- Items with a big gap between cheapest and average are potential flip opportunities.
- This is where your analytics brain will kick in.

**You will get stuck.** That's the point. When you do:

1. Read the error message carefully — Python error messages are actually helpful.
2. Try to fix it yourself for 5–10 minutes.
3. If stuck, ask Claude: paste the error and your code, ask *"Why is this happening and what should I learn from it?"* — not just *"Fix this."*

---

### Step 5 — Reflect (~15 mins)

Before you close your laptop, write a few quick notes to yourself:

- What worked?
- What confused you most?
- What would you want the tool to do next?

This becomes your plan for Session 2.

---

## What You Learned This Session

- **Python basics:** variables, f-strings, imports, working with dictionaries/lists
- **How APIs work:** HTTP methods (GET vs POST), headers, query parameters, status codes
- **OAuth2 authentication:** the most common auth pattern on the web
- **JSON:** the universal data format for APIs
- **Reading technical documentation:** a skill that separates engineers from tutorial-followers

---

## Useful References

| Resource | What It's For |
|----------|---------------|
| [Blizzard API Docs](https://develop.battle.net/documentation/world-of-warcraft/game-data-apis) | Endpoint reference — bookmark this |
| [Wowhead](https://www.wowhead.com) | Look up item IDs |
| [Python `requests` docs](https://docs.python-requests.org) | When you need to do something new with HTTP calls |
| [Python official tutorial](https://docs.python.org/3/tutorial/) | If you want to understand a concept more deeply |

---

## What's Coming in Session 2

You'll take this one-time snapshot and start **storing it in a database** so you can track prices over time. This is where it gets powerful — and where your existing SQL skills become directly useful.

---

## Ground Rules for Using Claude

- **Do ask:** "Explain [concept] to me" / "Why does this error happen?" / "What does this line do?"
- **Don't ask:** "Write the next function for me" / "Give me the code to do X"
- **Good habit:** After Claude explains something, close the chat and try to write it yourself from understanding, not from memory of Claude's code.
- If you're burning through messages, switch to reading the Python docs or Blizzard API docs directly. Getting comfortable with documentation is one of the most important skills you'll build.
