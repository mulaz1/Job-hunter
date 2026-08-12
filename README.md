# 🎯 Job Hunter

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg?logo=docker)](https://www.docker.com/)
[![Playwright](https://img.shields.io/badge/playwright-chromium-green.svg)](https://playwright.dev/)
[![SQLite](https://img.shields.io/badge/database-SQLite-003B57.svg?logo=sqlite)](https://www.sqlite.org/)
[![Telegram Bot API](https://img.shields.io/badge/telegram-bot%20api-26A5E4.svg?logo=telegram)](https://core.telegram.org/bots/api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An automated, self-hosted job board monitoring system built with Python, Playwright, and SQLite. **Job Hunter** continuously tracks corporate career pages across global tech enterprises, filters new listings against your personal skill keywords and location preferences, and delivers instant alerts straight to your **Telegram** device.

---

## 🌟 Key Features

- 🔌 **9+ Built-in Scraper Engines**: Native API clients and DOM parsers for major ATS platforms:
  - **Greenhouse** (JSON API)
  - **Workday** (REST API / Search endpoints)
  - **Lever** (Posting API)
  - **SmartRecruiters** (Public Job API)
  - **Eightfold AI** (API pagination)
  - **Workable** (Board API)
  - **Phenom People** (Careers Search API)
  - **XML Sitemap Crawler** (Automated job link discovery)
  - **Generic Headless Scraper** (Playwright Chromium for dynamic JavaScript single-page apps)
- 🎯 **Advanced Multi-Layer Filtering**:
  - **Keyword Include/Exclude**: Match relevant roles (e.g. `embedded systems`, `FPGA`, `firmware`) while filtering out noise (e.g. `frontend`, `sales`).
  - **Geographic Filtering**: Restrict job postings to selected countries (e.g. Western/Southern Europe) or allow remote/global roles.
- 🧠 **Smart Deduplication & History**:
  - SQLite database persists unique job fingerprints (`url` + `title` + `company`) so you never get notified twice for the same opening.
- 📲 **Telegram Notifications & Interactive Bot**:
  - Rich Markdown notifications sent in batches.
  - Interactive bot polling: add new companies on the fly using `/add <Company> <URL>` directly from Telegram!
- 🐳 **Docker-First & Low Footprint**:
  - Production-ready Docker Compose container with memory capping (1GB max), non-root user permissions, volume persistence, and automatic healthchecks.
- 🔒 **100% Private & Open Source**:
  - Zero telemetry or 3rd-party tracking. All scraped data and credentials stay on your server.

---

## 🏗️ Architecture & Workflow

```
             ┌──────────────────────────────────────────────┐
             │       APScheduler (Runs every N hours)        │
             └──────────────────────┬───────────────────────┘
                                    │
                                    ▼
             ┌──────────────────────────────────────────────┐
             │      Scraper Engine Dispatcher (src/)       │
             └──────┬───────────────┼───────────────┬───────┘
                    │               │               │
      ┌─────────────▼───┐   ┌───────▼──────┐   ┌────▼─────────────┐
      │ ATS APIs (JSON) │   │ XML Sitemaps │   │ Playwright Head- │
      │ Greenhouse/Lever│   │ Crawler      │   │ less Chromium    │
      │ Workday/Eightfold   │              │   │ (JS Dynamic Apps)│
      └─────────────┬───┘   └───────┬──────┘   └────┬─────────────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    │
                                    ▼
             ┌──────────────────────────────────────────────┐
             │       SQLite Database (data/jobs.db)         │
             │       (Deduplication & Fingerprinting)       │
             └──────────────────────┬───────────────────────┘
                                    │ New jobs only
                                    ▼
             ┌──────────────────────────────────────────────┐
             │     Filter Engine (src/filters.py)          │
             │   (Keyword Include/Exclude & Geo Check)      │
             └──────────────────────┬───────────────────────┘
                                    │ Matched jobs
                                    ▼
             ┌──────────────────────────────────────────────┐
             │      Telegram Bot API & Interactive Poll     │
             │    - Real-time Notifications                 │
             │    - `/add <Company> <URL>` command          │
             └──────────────────────────────────────────────┘
```

---

## 🛠️ Supported Scraper Engines

| Engine | Type | Sample URL Format | Description |
| :--- | :--- | :--- | :--- |
| `greenhouse` | REST API | `https://boards.greenhouse.io/company` | Official Greenhouse Job Board API. |
| `lever` | REST API | `https://jobs.lever.co/company` | Official Lever Postings API. |
| `workday` | REST API | `https://company.wd3.myworkdayjobs.com/...` | Workday external job board API. |
| `smartrecruiters` | REST API | `https://api.smartrecruiters.com/v1/companies/...` | SmartRecruiters public API. |
| `eightfold` | REST API | `https://company.eightfold.ai/careers` | Eightfold AI candidate portal API. |
| `workable` | REST API | `https://apply.workable.com/company/` | Workable postings API. |
| `phenom` | REST API | `https://careers.company.com/jobs` | Phenom People careers API. |
| `sitemap` | XML Crawler | `https://www.company.com/sitemap.xml` | Parses XML sitemaps for job detail URLs. |
| `generic` | Headless Browser | `https://company.com/careers` | Playwright Chromium engine for SPA/React/Angular career portals. |

---

## 🚀 Quick Start (Docker)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/job-hunter.git
cd job-hunter
```

### 2. Configure Environment Variables

Copy the template environment file:

```bash
cp .env.example .env
```

Edit `.env` to supply your Telegram credentials:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=987654321
SCAN_INTERVAL_HOURS=6
LOG_LEVEL=INFO
```

> **How to create a Telegram Bot:**
> 1. Message **[@BotFather](https://t.me/BotFather)** on Telegram and send `/newbot`.
> 2. Follow the prompt to get your **Bot Token**.
> 3. Start a chat with your bot, then get your **Chat ID** by visiting: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` (or use `@userinfobot`).

### 3. Configure Target Companies

Edit `config/companies.yml` to specify the companies and ATS scrapers you wish to monitor:

```yaml
companies:
  - name: STMicroelectronics
    country: Italy
    careers_url: https://stmicroelectronics.eightfold.ai/careers
    scraper: eightfold
    company_id: stmicroelectronics
    eightfold_domain: stmicroelectronics.com

  - name: NXP Semiconductors
    country: Netherlands
    careers_url: https://nxp.wd3.myworkdayjobs.com/careers
    scraper: workday
    company_id: nxp
    workday_tenant: nxp
    workday_instance: wd3

  - name: Exein
    careers_url: https://job-boards.eu.greenhouse.io/exeinspa
    scraper: greenhouse
    company_id: exeinspa

  - name: ASML
    country: Netherlands
    careers_url: https://www.asml.com/en/careers/find-your-job
    scraper: generic
```

### 4. Configure Search Filters

Edit `config/filters.yml` to specify desired keywords and allowed locations:

```yaml
include_keywords:
  - hardware engineer
  - embedded systems
  - firmware developer
  - fpga design
  - pcb layout

exclude_keywords:
  - frontend developer
  - web developer
  - sales manager
  - backend engineer

allowed_countries:
  - Italy
  - Germany
  - Netherlands
  - France
  - Switzerland
```

### 5. Build and Launch Container

```bash
# Build the Docker image
docker compose build

# Start in detached (background) mode
docker compose up -d
```

Check the logs in real time:

```bash
docker compose logs -f
```

---

## 🤖 Interactive Telegram Bot Commands

Once running, Job Hunter listens for commands in your Telegram chat:

- `/help` — Displays available commands and bot status.
- `/add <Company Name> <Careers URL>` — Dynamically registers a new company to `config/companies.yml`. The bot auto-detects the ATS platform (Workday, Greenhouse, Lever, Eightfold, Workable, Phenom, SmartRecruiters) and includes it in the next scan cycle!

**Example:**
```
/add Acme Corp https://boards.greenhouse.io/acmecorp
```

---

## ⚙️ Configuration Reference

### Directory Overview

```
job-hunter/
├── Dockerfile              # Python 3.12-slim + Playwright Chromium image
├── docker-compose.yml      # Service setup with volume persistence & resource limits
├── requirements.txt        # Dependencies (Playwright, httpx, APScheduler, PyYAML)
├── .env.example            # Environment variables template
├── config/
│   ├── companies.yml       # List of target companies & scraper settings
│   └── filters.yml         # Keyword & location filtering rules
├── data/
│   └── jobs.db             # Persistent SQLite database (auto-created)
├── src/
│   ├── main.py             # Entry point
│   ├── config.py           # Configuration loader & validation
│   ├── database.py         # SQLite persistence & query operations
│   ├── models.py           # Data structures (Job model)
│   ├── filters.py          # Keyword & geographic filtering logic
│   ├── telegram.py         # Telegram notifications & bot polling engine
│   ├── scheduler.py        # APScheduler orchestration loop
│   └── scrapers/           # Modular ATS scraper implementations
│       ├── base.py
│       ├── generic.py
│       ├── greenhouse.py
│       ├── lever.py
│       ├── workday.py
│       ├── smartrecruiters.py
│       ├── eightfold.py
│       ├── workable.py
│       ├── phenom.py
│       ├── sitemap.py
│       └── registry.py
└── tests/                  # Unit and integration test suite
```

---

## 💻 Local Development & Testing

If you prefer to run Job Hunter natively without Docker:

### 1. Python Environment Setup

```bash
# Prerequisites: Python 3.12+
python -m venv venv

# On Linux/macOS:
source venv/bin/activate
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium
```

### 2. Run the Application

```bash
python -m src.main
```

### 3. Run Test Suite

Job Hunter comes with a comprehensive test suite covering scrapers, filtering logic, and database operations.

```bash
# Run tests
python -m pytest tests/ -v

# Run tests with coverage report
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## ☁️ Deployment Guide (VPS / Server)

You can host Job Hunter 24/7 on any cheap Linux VPS (Hetzner, DigitalOcean, AWS EC2, Linode, Scaleway).

### Ubuntu/Debian Setup

```bash
# 1. Update system & install Docker
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git

# 2. Clone repository to /opt
sudo git clone https://github.com/your-username/job-hunter.git /opt/job-hunter
cd /opt/job-hunter

# 3. Configure env & config files
cp .env.example .env
nano .env

# 4. Start Docker container
docker compose build
docker compose up -d

# 5. Enable autostart on boot
sudo systemctl enable docker
```

---

## 🗄️ Database Management & Backup

All jobs are tracked in `data/jobs.db`. The SQLite database is mounted outside the container for seamless data persistence.

### Inspect Database Records

```bash
# Query recent jobs via sqlite3
sqlite3 data/jobs.db "SELECT company, title, location, first_seen_at FROM jobs ORDER BY first_seen_at DESC LIMIT 10;"

# Count discovered jobs per company
sqlite3 data/jobs.db "SELECT company, COUNT(*) FROM jobs GROUP BY company ORDER BY COUNT(*) DESC;"
```

### Create Backup

```bash
# Backup SQLite database
cp data/jobs.db "data/jobs_backup_$(date +%Y%m%d).db"
```

---

## 🤝 Adding a Custom Scraper Engine

Job Hunter's scraper architecture is modular and extensible. To add support for a new ATS or career site platform:

1. Create a new file in `src/scrapers/my_platform.py`:

```python
from src.models import Job
from src.scrapers.base import BaseScraper

class MyPlatformScraper(BaseScraper):
    def scrape(self) -> list[Job]:
        # Implement fetching & parsing logic
        jobs = []
        # ... fetch jobs ...
        return jobs
```

2. Register your class in `src/scrapers/registry.py`:

```python
from src.scrapers.my_platform import MyPlatformScraper

# Add to _get_scrapers() dictionary:
"my_platform": MyPlatformScraper,
```

3. Specify `scraper: my_platform` in `config/companies.yml`.

---

## 🛡️ Security & Privacy

- **No Third-Party Analytics**: Job Hunter sends data **only** to the official Telegram Bot API endpoint (`https://api.telegram.org`).
- **Secrets Protection**: `.env` and SQLite database files (`data/*.db`) are ignored by Git.
- **Least Privilege**: The Docker container executes under a non-root system user (`appuser`).

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.
