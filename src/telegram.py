"""Telegram notification module for Job Hunter."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
import yaml

from src.config import TelegramConfig
from src.models import Job

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = 30  # seconds


def _format_job_message(job: Job) -> str:
    location = job.location or "Location not specified"
    lines = [
        "🆕 *NUOVA POSIZIONE*",
        "",
        f"*{_escape_markdown(job.title)}*",
        "",
        f"🏢 {_escape_markdown(job.company)}",
        f"📍 {_escape_markdown(location)}",
        "",
        f"🔗 {_escape_markdown(job.url)}",
    ]
    return "\n".join(lines)


def _format_batch_message(jobs: list[Job], batch_num: int, total_batches: int) -> str:
    header = "🔔 *Job Hunter — Nuove Posizioni*"
    if total_batches > 1:
        header += f" \\({batch_num}/{total_batches}\\)"

    parts = [header, ""]
    for i, job in enumerate(jobs, 1):
        location = job.location or "Location not specified"
        parts.append(f"*{i}\\. {_escape_markdown(job.title)}*")
        parts.append(f"🏢 {_escape_markdown(job.company)} · 📍 {_escape_markdown(location)}")
        parts.append(f"🔗 {_escape_markdown(job.url)}")
        parts.append("")

    return "\n".join(parts).strip()


def _escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if not text:
        return ""
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    result = ""
    for char in text:
        if char in special_chars:
            result += "\\" + char
        else:
            result += char
    return result


class TelegramNotifier:
    """
    Sends job notifications via Telegram Bot API.

    If not configured (no token/chat_id), all send methods are no-ops.
    """

    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        self.max_jobs_per_message = config.max_jobs_per_message
        self._running = False
        self._polling_thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        self._http_client: Optional[httpx.Client] = None

        if not config.is_configured:
            logger.warning(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable notifications."
            )

    def _get_api_url(self, method: str) -> str:
        """Build a Telegram Bot API URL. Token is not logged."""
        return f"{TELEGRAM_API_BASE}/bot{self.config.bot_token}/{method}"

    def send_message(self, text: str) -> bool:
        if not self.config.is_configured:
            logger.debug("Telegram not configured, skipping message.")
            return False

        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.post(
                    self._get_api_url("sendMessage"),
                    json=payload,
                )
            if response.status_code == 200:
                logger.debug("Telegram message sent successfully.")
                return True
            else:
                logger.error(
                    "Telegram API error %d: %s",
                    response.status_code,
                    response.text[:200],  # Truncate to avoid leaking content
                )
                return False
        except httpx.TimeoutException:
            logger.error("Telegram request timed out after %ds", REQUEST_TIMEOUT)
            return False
        except httpx.RequestError as e:
            logger.error("Telegram request failed: %s", e)
            return False

    def send_jobs(self, jobs: list[Job]) -> tuple[int, int]:
        if not jobs:
            return 0, 0

        if not self.config.is_configured:
            logger.warning(
                "Telegram not configured — %d jobs would have been notified.", len(jobs)
            )
            return 0, len(jobs)

        batches: list[list[Job]] = []
        for i in range(0, len(jobs), self.max_jobs_per_message):
            batches.append(jobs[i : i + self.max_jobs_per_message])

        total_batches = len(batches)
        sent = 0
        failed = 0

        for batch_num, batch in enumerate(batches, 1):
            message = _format_batch_message(batch, batch_num, total_batches)
            success = self.send_message(message)
            if success:
                sent += len(batch)
                logger.info(
                    "Telegram batch %d/%d sent (%d jobs)",
                    batch_num,
                    total_batches,
                    len(batch),
                )
            else:
                failed += len(batch)
                logger.error(
                    "Telegram batch %d/%d FAILED (%d jobs not notified)",
                    batch_num,
                    total_batches,
                    len(batch),
                )

        return sent, failed

    def send_startup_message(self) -> None:
        if not self.config.is_configured:
            return
        text = (
            "🚀 *Job Hunter avviato*\n\n"
            "Il monitoraggio delle offerte di lavoro è attivo\\.\n"
            "Riceverai notifiche per le nuove posizioni corrispondenti ai tuoi filtri\\.\n"
            "Usa `/help` per visualizzare i comandi disponibili\\."
        )
        self.send_message(text)

    def start_polling(self) -> None:
        if not self.config.is_configured:
            return
        if self._running:
            return
        self._running = True
        self._polling_thread = threading.Thread(target=self._poll_updates, daemon=True)
        self._polling_thread.start()
        logger.info("Telegram polling started.")

    def stop_polling(self) -> None:
        self._running = False
        if self._http_client:
            try:
                self._http_client.close()
            except Exception:
                pass
            self._http_client = None
        if self._polling_thread:
            self._polling_thread.join(timeout=2)
            logger.info("Telegram polling stopped.")

    def _poll_updates(self) -> None:
        # Long polling client with 45s read timeout (Telegram server timeout is 20s)
        polling_timeout = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)
        
        while self._running:
            try:
                if self._http_client is None or self._http_client.is_closed:
                    self._http_client = httpx.Client(timeout=polling_timeout)

                response = self._http_client.get(
                    self._get_api_url("getUpdates"),
                    params={"offset": self._last_update_id, "timeout": 20},
                )
                if response.status_code == 200:
                    data = response.json()
                    for update in data.get("result", []):
                        self._last_update_id = max(self._last_update_id, update["update_id"] + 1)
                        self._handle_update(update)
                elif response.status_code == 409:
                    logger.warning("Telegram polling 409 Conflict: another instance may be running.")
                    time.sleep(10)
                else:
                    logger.warning("Telegram getUpdates status %d: %s", response.status_code, response.text[:200])
                    time.sleep(5)
            except httpx.TimeoutException:
                # Normal when no messages arrive within long polling window
                pass
            except (httpx.RequestError, httpx.HTTPError) as e:
                logger.warning("Telegram polling network error (retrying in 5s): %s", e)
                if self._http_client:
                    try:
                        self._http_client.close()
                    except Exception:
                        pass
                    self._http_client = None
                time.sleep(5)
            except Exception as e:
                logger.error("Telegram polling unexpected error (retrying in 5s): %s", e, exc_info=True)
                if self._http_client:
                    try:
                        self._http_client.close()
                    except Exception:
                        pass
                    self._http_client = None
                time.sleep(5)

    def _handle_update(self, update: dict) -> None:
        message = update.get("message")
        if not message:
            return
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")
        
        if str(chat_id) != str(self.config.chat_id):
            return

        if text == "/help":
            self._handle_help_command()
        elif text.startswith("/add"):
            self._handle_add_command(text)
        elif text.startswith("/"):
            self.send_message(f"⚠️ Comando non riconosciuto: `{_escape_markdown(text)}`\nUsa `/help` per la lista dei comandi\\.")

    def _handle_help_command(self) -> None:
        text = (
            "🤖 *Job Hunter Bot — Guida*\n\n"
            "✅ *Comandi Disponibili:*\n"
            "• `/help` \\- Mostra questo messaggio\n"
            "• `/add <Azienda> <URL>` \\- Aggiunge un sito careers\\.\n\n"
            "❌ *Comandi NON ancora disponibili:*\n"
            "• `/scan` \\- Forza scansione immediata\n"
            "• `/stats` \\- Statistiche database\n"
            "• `/pause` \\- Sospende le notifiche\n"
        )
        self.send_message(text)

    def _handle_add_command(self, text: str) -> None:
        parts = text.split()
        if len(parts) < 3:
            self.send_message("⚠️ *Sintassi errata*\nUso corretto: `/add Nome Azienda https://...`")
            return
            
        url = parts[-1]
        company_name = " ".join(parts[1:-1])
        
        if not url.startswith("http"):
            self.send_message("⚠️ L'URL deve iniziare con `http://` o `https://`")
            return
            
        scraper = "generic"
        if "myworkdayjobs.com" in url:
            scraper = "workday"
        elif "greenhouse.io" in url or "boards.greenhouse.io" in url:
            scraper = "greenhouse"
        elif "lever.co" in url or "jobs.lever.co" in url:
            scraper = "lever"
        elif "smartrecruiters.com" in url:
            scraper = "smartrecruiters"
        elif "eightfold.ai" in url:
            scraper = "eightfold"
        elif "workable.com" in url:
            scraper = "workable"
        elif "phenom.com" in url or "phenompro.com" in url:
            scraper = "phenom"
            
        config_path = Path("config/companies.yml")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                
            companies = content.get("companies", [])
            
            for c in companies:
                if c.get("name", "").lower() == company_name.lower():
                    self.send_message(f"⚠️ L'azienda `{_escape_markdown(company_name)}` è già presente in configurazione\\.")
                    return
            
            new_company = {
                "name": company_name,
                "careers_url": url,
                "scraper": scraper
            }

            if scraper == "greenhouse":
                from src.scrapers.greenhouse import _extract_board_token_from_url
                cid = _extract_board_token_from_url(url)
                if cid:
                    new_company["company_id"] = cid
            elif scraper == "lever":
                from src.scrapers.lever import _extract_company_id_from_url
                cid = _extract_company_id_from_url(url)
                if cid:
                    new_company["company_id"] = cid
            elif scraper == "smartrecruiters":
                from src.scrapers.smartrecruiters import _extract_company_id_from_url
                cid = _extract_company_id_from_url(url)
                if cid:
                    new_company["company_id"] = cid
            elif scraper == "workable":
                from src.scrapers.workable import _extract_tenant_from_url
                cid = _extract_tenant_from_url(url)
                if cid:
                    new_company["company_id"] = cid
            elif scraper == "eightfold":
                from src.scrapers.eightfold import _extract_tenant_from_url
                cid = _extract_tenant_from_url(url)
                if cid:
                    new_company["company_id"] = cid
                    new_company["eightfold_domain"] = f"{cid}.com"
            elif scraper == "workday":
                from src.scrapers.workday import _extract_tenant_from_url
                tenant, instance = _extract_tenant_from_url(url)
                if tenant and instance:
                    new_company["company_id"] = tenant
                    new_company["workday_tenant"] = tenant
                    new_company["workday_instance"] = instance

            companies.append(new_company)
            content["companies"] = companies
            
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(content, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                
            self.send_message(
                f"✅ *Azienda Aggiunta\\!*\n\n"
                f"🏢 *Nome:* {_escape_markdown(company_name)}\n"
                f"⚙️ *Scraper:* {_escape_markdown(scraper)}\n"
                f"🔗 *URL:* {_escape_markdown(url)}\n\n"
                "La nuova azienda sarà inclusa a partire dalla prossima scansione programmata\\."
            )
            
            # We rely on the scheduler to reload the config before the next scan
            
            logger.info("Added new company via Telegram: %s", company_name)
        except Exception as e:
            logger.error("Error adding company: %s", e)
            self.send_message("❌ Si è verificato un errore durante l'aggiunta dell'azienda\\.")

    def test_connection(self) -> bool:
        if not self.config.is_configured:
            return False
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(self._get_api_url("getMe"))
            ok = response.status_code == 200 and response.json().get("ok", False)
            if ok:
                bot_name = response.json().get("result", {}).get("username", "unknown")
                logger.info("Telegram connection OK (bot: @%s)", bot_name)
            else:
                logger.error("Telegram connection test failed: %s", response.text[:200])
            return ok
        except Exception as e:
            logger.error("Telegram connection test error: %s", e)
            return False
