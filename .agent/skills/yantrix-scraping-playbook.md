# Skill: Yantrix Scraping & Auditing Playbook (yantrix-scraping-playbook)

## Data Collection Ethics & Constraints
*   **Rule 1: Public Data Only.** We only scrape publicly available business information (Business Name, Address, Category, Phone, Public Email, Website URL).
*   **Rule 2: No PII.** Do not attempt to extract personal employee data, private emails, or protected personal identifiable information.
*   **Rule 3: Respect Rate Limits.** Aggressive scraping acts like a DDoS. Always implement concurrency limits and jitter (random delays).
*   **Rule 4: No Access Bypass.** Never bypass logins, CAPTCHAs, or access controls.

## Tooling & Orchestration

### 1. Google Maps Discovery (`gosom/google-maps-scraper`)
*   **Role:** Primary source for business discovery.
*   **Integration:** Runs as a standalone Docker sidecar.
*   **Usage:** Do not write custom Selenium scripts for GMaps. Instead, make REST calls from FastAPI to `http://gmaps-scraper:8080/api/v1/jobs`. Submit a query, poll for completion, and parse the resulting CSV.

### 2. Website Auditing (Playwright)
*   **Role:** Deep analysis of target websites.
*   **Stack:** `async_playwright` with Chromium.
*   **Concurrency:** CRITICAL. You must use `asyncio.Semaphore(settings.AUDIT_CONCURRENCY)` (e.g., max 5) to prevent blowing up the VM's RAM.
*   **Heuristics to Implement:**
    *   *Mobile Friendly:* Emulate a mobile viewport (`375x812`). Check for `<meta name="viewport">`.
    *   *WhatsApp:* Look for `href` containing `wa.me` or `api.whatsapp.com`.
    *   *Booking:* Look for iframes or links to `calendly.com`, `acuityscheduling.com`, etc.
    *   *CTA/Forms:* Query `form` elements and buttons containing keywords like "Book", "Contact", "Schedule".
    *   *SEO/Social:* Check for title, meta description, H1, OG tags, and public social profile links.
*   **Timeouts:** Always enforce strict timeouts (`page.goto(url, timeout=30000)`). If a site fails, mark the audit as skipped/failed; do not block the queue.

### 3. JustDial Scraper (Optional/Fallback)
*   **Role:** Secondary discovery.
*   **Constraints:** JustDial heavily blocks automated traffic. This module must be feature-flagged (`JUSTDIAL_ENABLED=False` by default).
*   **Technique:** If enabled, use Playwright with stealth techniques. Add significant random sleep jitter (3-8 seconds) between page loads.

## Agent Instructions
*   Read `CODEX_PROMPT.md` and `ARCHITECTURE.md` if the target scraping behavior or compliance boundary is unclear.
*   When writing scraping logic, prioritize robustness. Websites are messy; wrap extractions in `try/except` blocks.
*   Never use blocking libraries (`requests`, `selenium`, synchronous `BeautifulSoup`) inside the FastAPI async loop.
*   Ground downstream scoring and pitch generation only in observed public signals. Do not infer facts that were not detected.
