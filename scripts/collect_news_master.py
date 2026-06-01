# -*- coding: utf-8 -*-
"""
Daily News Collector - Master Script
Usage: python collect_news_master.py [start_date YYYY-MM-DD] [end_date YYYY-MM-DD]
Reads XRZ_WORKDIR env var for output directory.
"""
import sys, os, json, re, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ===================== Config =====================
BASE_DIR = Path(os.environ.get('XRZ_WORKDIR', r'C:\Users\X.LAPTOP-CA1GJQE3\Desktop\2025-2026_News_Archive'))
DAILY_DIR = BASE_DIR / 'daily_news'
MONTHLY_DIR = BASE_DIR / 'monthly_summaries'
SCRIPT_DIR = BASE_DIR / 'scripts'
DAILY_DIR.mkdir(parents=True, exist_ok=True)
MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
SCRIPT_DIR.mkdir(parents=True, exist_ok=True)

MAX_PAGES = 3
SEARCH_DELAY = 1.5  # seconds between requests

# ===================== Progress File =====================
PROGRESS_FILE = DAILY_DIR / '_progress.json'

def save_progress(current_date, total, done, skip, status='running'):
    progress = {
        'current': current_date.strftime('%Y-%m-%d') if current_date else None,
        'total_days': total,
        'done': done,
        'skip': skip,
        'status': status,
        'last_update': datetime.now().isoformat(),
    }
    try:
        PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    return progress

# ===================== Search Function =====================
def search_bing(query, max_pages=3):
    """Search Bing with urllib, return text summaries"""
    results = []
    enc_q = urllib.parse.quote_plus(query)

    for page in range(max_pages):
        offset = page * 10
        url = f"https://cn.bing.com/search?q={enc_q}&first={offset}&FORM=PERE"

        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', errors='ignore')

            # Method 1: li.b_algo card structure
            cards = re.findall(
                r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
                html, re.DOTALL
            )

            for card in cards[:5]:
                # Extract title - multiple possible patterns
                title = ''
                for title_pat in [
                    r'<h2[^>]*>(?:<a[^>]*>){1,2}([^<]+)</a>',
                    r'<h2[^>]*>.*?<a[^>]*>([^<]+)</a>',
                ]:
                    tm = re.search(title_pat, card, re.DOTALL)
                    if tm:
                        title = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
                        break

                # Extract snippet - multiple patterns
                snippet = ''
                for pat in [
                    r'<p[^>]*class="[^"]*b_paractip[^"]*"[^>]*>([^<]+)</p>',
                    r'<p[^>]*>([^<]{40,800})</p>',
                ]:
                    sm = re.search(pat, card)
                    if sm:
                        snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                        snippet = re.sub(r'\s+', ' ', snippet)
                        break

                if title and len(title) > 3:
                    results.append(f"- {title[:80]}: {snippet[:200]}")

            # Method 2: fallback - extract paragraphs from raw HTML
            if not results:
                paras = re.findall(r'<p[^>]*>([^<]{60,1000})</p>', html)
                for para in paras[:8]:
                    clean = re.sub(r'<[^>]+>', '', para).strip()
                    clean = re.sub(r'\s+', ' ', clean)
                    if len(clean) > 50 and clean not in results:
                        results.append(f"- {clean[:300]}")

            if len(results) >= 5:
                break

        except Exception as e:
            print(f"[SEARCH ERROR page{page+1}] {e}", file=sys.stderr)

        import time
        time.sleep(SEARCH_DELAY)

    if results:
        return '\n'.join(results[:10])
    return f"[NO RESULTS] Query: {query}"

# ===================== News Categories =====================
CATEGORIES = [
    ("International", "major international news diplomacy"),
    ("Technology", "tech AI chip internet breakthrough"),
    ("Finance", "stock market economy data earnings"),
]

# ===================== Date Range =====================
if len(sys.argv) >= 3:
    start_date = datetime.strptime(sys.argv[1], '%Y-%m-%d')
    end_date = datetime.strptime(sys.argv[2], '%Y-%m-%d')
else:
    end_date = datetime.today() - timedelta(days=1)
    start_date = datetime(2025, 1, 1)

total_days = (end_date - start_date).days + 1
print(f"[INFO] Start: {start_date.strftime('%Y-%m-%d')} -> {end_date.strftime('%Y-%m-%d')}, {total_days} days total", file=sys.stderr)
print(f"[INFO] Output: {DAILY_DIR}", file=sys.stderr)

save_progress(start_date, total_days, 0, 0, 'running')

current = start_date
done_count = 0
skip_count = 0

while current <= end_date:
    date_str = current.strftime('%Y-%m-%d')
    filename = DAILY_DIR / f"{date_str}.md"

    if filename.exists():
        skip_count += 1
        current += timedelta(days=1)
        continue

    sections = []
    sections.append(f"# {date_str} Daily News\n\n")
    sections.append(f"> Collected: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    sections.append("---\n\n")

    for cat_name, cat_desc in CATEGORIES:
        query = f"{date_str} {cat_desc}"
        content = search_bing(query, MAX_PAGES)
        sections.append(f"## {cat_name}\n\n{content}\n\n")

    # Write file
    try:
        filename.write_text(''.join(sections), encoding='utf-8')
        done_count += 1
        print(f"[OK] {date_str} done={done_count} skip={skip_count}", file=sys.stderr)
    except Exception as e:
        print(f"[FAIL] {date_str} write error: {e}", file=sys.stderr)

    save_progress(current, total_days, done_count, skip_count, 'running')
    current += timedelta(days=1)

# ===================== Monthly Summaries =====================
save_progress(current, total_days, done_count, skip_count, 'done')
print(f"\n[DONE] {done_count} days collected, {skip_count} skipped", file=sys.stderr)

months = sorted(set(f.stem[:7] for f in DAILY_DIR.glob('*.md')))
print(f"[MONTHLY] Found {len(months)} months: {months}", file=sys.stderr)

for ym in months[-3:]:
    summary_file = MONTHLY_DIR / f"{ym}_summary.md"
    if summary_file.exists():
        print(f"[SKIP] {ym} summary already exists", file=sys.stderr)
        continue

    year, month = ym.split('-')
    month_files = sorted(DAILY_DIR.glob(f"{ym}-*.md"))
    print(f"[MONTHLY] Generating {ym} from {len(month_files)} days ...", file=sys.stderr, end='')

    lines = [f"# {year}-{month} Monthly Summary\n\n"]
    lines.append(f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    lines.append("---\n\n")

    for cat_name, _ in CATEGORIES:
        lines.append(f"## {cat_name}\n\n")
        events = []
        for day_file in month_files:
            content = day_file.read_text(encoding='utf-8', errors='ignore')
            # Extract category section
            m = re.search(rf'## {cat_name}\s*\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
            if m:
                section = m.group(1).strip()[:600]
                date_label = day_file.stem
                if section and '[NO RESULTS]' not in section and '当日搜索无结果' not in section:
                    events.append(f"**{date_label}**: {section[:300]}")
        if events:
            lines.append('\n'.join(events[:15]))
        else:
            lines.append("No major events this month.")
        lines.append('\n\n---\n\n')

    lines.append("## Event Correlation Analysis\n\n")
    lines.append("*Manual analysis of major events and their correlations pending.*\n")
    lines.append(f"\nSource files: {', '.join(f.name for f in month_files[:5])}...\n")

    try:
        summary_file.write_text(''.join(lines), encoding='utf-8')
        print(f" -> {summary_file.name}", file=sys.stderr)
    except Exception as e:
        print(f" [FAIL] {e}", file=sys.stderr)

print(f"\n[COMPLETE] All tasks done.", file=sys.stderr)
