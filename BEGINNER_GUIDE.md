# RE_OS — Complete Beginner's Guide
### What everything is, why it exists, and exactly what to do

---

## Before We Start — The Big Picture

Think of what we're building like a small office with specialized staff:

- **The Office Building** = Docker. It's a controlled environment on your computer where the team lives. Nothing leaks out, nothing interferes with your normal computer.
- **The Database** = PostgreSQL. The filing cabinet. Every RERA project, every listing, every price — stored here permanently.
- **The Local AI** = Ollama. A free AI model that runs on your own machine. Does the boring reading and parsing work. Costs you nothing.
- **The Cloud AI** = OpenRouter. Free access to powerful AI models (Llama, Gemma) for smarter analysis. Also free.
- **The Agents** = Five specialists (CEO, Scraper, Parser, Organizer, Analyst) that work together automatically.

When it's all running, here's what happens without you doing anything:
- Every night at 2 AM: the system scrapes RERA Karnataka for all Yelahanka projects
- Every morning at 6 AM: it computes the market intelligence report
- It stores everything in a database that gets smarter over time

You ask it a question. It answers with real data.

---

## PHASE 1: Install Docker Desktop
### "The Office Building"

**What is Docker?**
Normally, when you install software on Windows, it touches your whole computer — registry entries, system files, conflicts with other software. Docker is different. It runs software in isolated "containers" — like running a separate mini-computer inside your computer. The PostgreSQL database, the AI, the agents — they all live in their own containers, talk to each other, and don't touch the rest of your machine. When you're done with the project, one command deletes everything cleanly.

**Step 1.1 — Download Docker Desktop**

1. Open Chrome or Edge
2. Go to: **https://www.docker.com/products/docker-desktop/**
3. Click **"Download for Windows"**
4. The file is about 500MB — let it download

**Step 1.2 — Install Docker Desktop**

1. Double-click the downloaded file (`Docker Desktop Installer.exe`)
2. It will ask about WSL 2 — **tick the box and say yes**
   - WSL 2 = "Windows Subsystem for Linux" — lets Docker run Linux containers on Windows
   - If it asks you to install WSL, say yes and follow the prompts
3. Click through the installer with default settings
4. When it says "Installation succeeded" — **restart your computer**

**Step 1.3 — Verify Docker is running**

After restart:
1. Look for the Docker whale icon in your system tray (bottom-right of taskbar, near the clock)
2. Click it — it should say **"Docker Desktop is running"** with a green light
3. If it says "Starting..." — wait 2 minutes, it's booting up

**What you've done:** You now have the office building. Empty, but ready.

---

## PHASE 2: Open a Terminal
### "The Command Line — How You Talk to Your Computer Directly"

**What is a Terminal?**
Usually you click things to make them happen. A terminal is where you type instructions directly. It feels old-fashioned but it's actually much faster for technical work. Don't be intimidated — every command I give you, you just copy-paste.

**Step 2.1 — Open Windows Terminal**

Press `Windows key + R`, type `cmd`, press Enter.

A black window opens. This is your terminal.

Alternatively: search for "Command Prompt" or "Windows Terminal" in the Start menu.

**Step 2.2 — Navigate to your RE_OS folder**

Type this exactly and press Enter:
```
cd "D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS"
```

You should now see the path in your terminal. You're "inside" the RE_OS folder.

**What "cd" means:** "Change Directory" — same as double-clicking a folder to open it, but in terminal.

---

## PHASE 3: Install Ollama
### "The Free Local AI — Does the Reading and Parsing Work"

**What is Ollama?**
When you scrape RERA Karnataka, you get messy data — HTML tables, inconsistent field names, Indian price formats like "₹45L" or "1.2 Crore". A regular program can't interpret that. You need an AI that reads like a human. Ollama lets you run a powerful AI model (Llama 3.1 — the same family as ChatGPT's competitors) completely free, on your own machine, forever. No subscription, no API limits, no internet needed once downloaded.

It's doing the **grunt work** — reading 500 RERA entries and converting them into clean database rows. We don't waste your Claude subscription on that.

**Step 3.1 — Download Ollama**

1. Go to: **https://ollama.ai**
2. Click **"Download for Windows"**
3. Install it (default settings, no special configuration needed)

**Step 3.2 — Download the AI Model**

Open your terminal (or use the one already open) and type:
```
ollama pull llama3.1:8b
```
Press Enter.

This downloads the Llama 3.1 8 Billion parameter model. It's about 5GB. 

You'll see a progress bar. Let it run. This is a one-time download.

**What "8b" means:** The model has 8 billion parameters — think of it as how many "connections" the AI has learned. 8B is good enough for parsing and structuring data. It's not the smartest model in the world, but for reading RERA tables, it's more than enough — and it's free.

**Step 3.3 — Verify Ollama is working**

Type this in terminal:
```
ollama list
```

You should see `llama3.1:8b` in the list. That means it's installed and ready.

---

## PHASE 4: Get OpenRouter API Key
### "The Free Cloud AI — Does the Smarter Analysis"

**What is OpenRouter?**
Some tasks need a smarter AI — like the Analyst agent figuring out whether Yelahanka's 38% absorption rate is a red flag or normal for the segment, or the CEO agent synthesizing a strategic read. For that, we use OpenRouter — a service that gives you free access to high-quality models like Meta's Llama 3.1 and Google's Gemma.

Free tier gives you access with no credit card needed. The free models are more than capable for market analysis.

**Step 4.1 — Create OpenRouter account**

1. Go to: **https://openrouter.ai**
2. Click **"Sign In"** → **"Continue with Google"**
3. Use your Gmail (jinujon007@gmail.com or whichever you prefer)

**Step 4.2 — Create an API Key**

1. Once logged in, click your profile icon (top right)
2. Click **"API Keys"**
3. Click **"Create Key"**
4. Name it: `RE_OS`
5. Click **"Create"**
6. A key appears — it starts with `sk-or-v1-...`
7. **Copy it immediately** — you won't see it again (but you can create a new one if you lose it)

**What is an API Key?**
Think of it as a password that lets software use a service on your behalf. When RE_OS calls OpenRouter for analysis, it sends this key to prove it's your account. OpenRouter tracks usage against your account's free limit.

---

## PHASE 5: Configure RE_OS
### "Tell the System Who You Are and What You Want"

**Step 5.1 — Create the .env file**

In your terminal (make sure you're in the RE_OS folder), type:
```
copy .env.example .env
```

This creates a configuration file called `.env` (the dot at the start means it's a hidden settings file).

**Step 5.2 — Edit the .env file**

Open File Explorer, go to:
`D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`

You'll see a file called `.env` (might show as just `env` if file extensions are hidden).

Right-click it → Open with → Notepad

You'll see:
```
DB_PASSWORD=re_os_2024
OPENROUTER_API_KEY=sk-or-v1-your-key-here
TARGET_MARKETS=Yelahanka,Devanahalli,Hebbal
OLLAMA_MODEL=llama3.1:8b
```

Replace `sk-or-v1-your-key-here` with the actual key you copied from OpenRouter.

Save the file (Ctrl+S). Close Notepad.

**What is .env?**
Environment variables. Instead of hardcoding secrets into your code (bad practice — if you share code, you share secrets), you put them in a .env file that stays only on your machine. The system reads this file on startup to know: what's my database password? what's my API key? which markets am I watching?

---

## PHASE 6: Boot the System
### "Start the Office and Hire the Staff"

This is the moment. One command starts everything.

**Step 6.1 — Make sure you're in the right folder**

In terminal:
```
cd "D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS"
```

**Step 6.2 — Start all containers**

```
docker compose up -d
```

Press Enter. Watch what happens.

Docker will:
1. Download the PostgreSQL+PostGIS image (~400MB) — one time only
2. Download Redis image (~30MB) — one time only
3. Build the agents container from your code
4. Start all five services

You'll see lines like:
```
✔ Container re_os_db        Started
✔ Container re_os_ollama    Started
✔ Container re_os_redis     Started
✔ Container re_os_agents    Started
✔ Container re_os_scheduler Started
```

**What "-d" means:** "Detached mode" — run in the background. The containers keep running even when you close this terminal window. They'll restart automatically when you reboot your computer.

**Step 6.3 — Check everything is healthy**

```
docker compose ps
```

You should see all containers with status `running` or `healthy`. If PostgreSQL says `healthy`, the database is ready.

**Step 6.4 — Load the Ollama model into Docker**

The Ollama container needs the model too:
```
docker exec re_os_ollama ollama pull llama3.1:8b
```

This may take a few minutes. The model downloads into the Docker container's storage.

---

## PHASE 7: Run Your First Intelligence Scan
### "Watch the System Actually Work"

**Step 7.1 — Scrape Yelahanka RERA data**

```
docker exec re_os_agents python scrapers/rera_karnataka.py --market Yelahanka
```

What this does:
- Goes to rera.karnataka.gov.in
- Searches for all projects in Yelahanka
- Pulls: RERA number, project name, developer, units launched, units sold, status
- Saves to: `RE_OS/outputs/yelahanka/rera_projects_[timestamp].json`

You'll see it working in real time — logging each step.

**Step 7.2 — Open the output file**

Go to: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS\outputs\yelahanka\`

Open the JSON file with Notepad (or VS Code if you have it).

You're looking at real RERA data — every registered project in Yelahanka, structured and clean. This is data that normally takes hours of manual searching on a government portal.

**Step 7.3 — Run the full intelligence crew**

```
docker exec re_os_agents python crews/market_intel_crew.py --market Yelahanka
```

This runs all five agents in sequence:
1. Scraper pulls RERA + listings data
2. Parser normalizes it
3. Organizer stores it in PostgreSQL
4. Analyst computes absorption rates, pricing, risk flags
5. CEO synthesizes the final market brief

Output lands in: `RE_OS/outputs/yelahanka/intel_report_[timestamp].txt`

Open it. That's your market intelligence brief.

---

## PHASE 8: Day-to-Day Usage
### "How You Live With This System"

**The system is now running in the background 24/7.**

Every morning you can open a new output file and read the overnight analysis. Or query it manually whenever you need.

**Useful commands:**

```bash
# Get a fresh market brief without scraping (uses existing DB data — instant)
docker exec re_os_agents python crews/market_intel_crew.py --report-only Yelahanka

# Scrape a specific market manually
docker exec re_os_agents python scrapers/rera_karnataka.py --market Devanahalli

# Run the full crew for all markets
docker exec re_os_agents python crews/market_intel_crew.py

# Check system logs (what's been happening)
docker compose logs --tail=50 agents

# Stop the system (when you want to)
docker compose stop

# Start it again
docker compose start

# Full restart (if something's stuck)
docker compose restart
```

**Add a new market:**
1. Open `.env`
2. Add the market to `TARGET_MARKETS=Yelahanka,Devanahalli,Hebbal,Whitefield`
3. Run: `docker compose restart agents scheduler`

**See what's in the database:**
When we build the query interface (next phase), you'll be able to ask questions like a search engine. For now, the output files are your window into the data.

---

## What You've Built — In Plain English

| Component | What it is | Why it matters |
|-----------|-----------|----------------|
| Docker | The container that holds everything | Portable, clean, won't break your computer |
| PostgreSQL + PostGIS | The database | Every project, price, developer — stored forever and queryable |
| Ollama (Llama 3.1) | Free local AI | Reads messy RERA data, converts to clean records — no cost ever |
| OpenRouter | Free cloud AI | Smart analysis — absorption trends, risk flags, market reads |
| Scraper Agent | Data collector | Goes to RERA Karnataka, pulls all projects for your markets |
| Parser Agent | Data cleaner | Turns "₹45L" and "45 Lakh" and "4500000" into the same number |
| Organizer Agent | Database keeper | Stores clean data, prevents duplicates, tracks what changed |
| Analyst Agent | Intelligence engine | Computes absorption, flags risk, identifies pricing white space |
| CEO Agent | Synthesizer | Reads all analysis, produces the strategic brief you act on |
| Scheduler | The clock | Runs everything automatically at 2 AM and 6 AM |

**What you know now that you didn't before:**
- Docker is not magic — it's just isolated containers
- Ollama is a free AI running on your machine — no subscription, no limits
- An API key is just a password for a service
- .env files keep secrets out of code
- Agents are just specialized programs with specific roles — not magic either

---

## Troubleshooting

**"Docker is not recognized"** — Docker Desktop isn't installed or isn't running. Open Docker Desktop from the Start menu first.

**"Container keeps restarting"** — Check logs: `docker compose logs agents`. Usually means a configuration error in .env.

**"0 projects found" from RERA scraper** — The RERA portal may have changed its structure. Check `RE_OS/logs/rera_scraper.log`. This is normal occasionally — government portals change. We fix the scraper and re-run.

**"Ollama model not found"** — Run `docker exec re_os_ollama ollama pull llama3.1:8b` again.

**System feels slow** — Ollama's 8B model needs RAM. If your machine has 8GB RAM, it'll be slow. 16GB+ is ideal. You can switch to a smaller model: edit `.env`, set `OLLAMA_MODEL=phi3:mini` and restart.

---

*Built: May 2026 | RE_OS v0.1 | Yelahanka seed market*
