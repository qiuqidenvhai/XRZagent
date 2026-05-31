#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, json, time, re, os, urllib.request, urllib.parse
from pathlib import Path

RESULT_PATH = "None\\result_1780191370853.json"
STATUS_PATH = "None\\status_1780191370853.txt"
QUERY = "Windows 11 \u6700\u65b0\u529f\u80fd 2026"
MAX_PAGES = "5"
WORK_DIR = "None"
COOKIE_DIR = "C:\\Users\\X.LAPTOP-CA1GJQE3\\.xianrenzhang_agent"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = "[" + ts + "] " + msg
    print(line, flush=True)

def set_status(status):
    Path(STATUS_PATH).write_text(status, encoding="utf-8")

def build_search_urls(query, max_pages):
    if not query: return []
    results = []
    if "://" in query: results.append(query)
    else:
        encoded = urllib.parse.quote(query, safe='')
        results.append("https://www.bing.com/search?q=" + encoded + "&mkt=zh-CN")
        results.append("https://www.google.com/search?q=" + encoded)
    mp = int(max_pages) if str(max_pages).isdigit() else 5
    return results[:mp]

def fetch(url, timeout=15):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.geturl()
    except Exception as e:
        return None, str(e)

def extract_text(html):
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s{2,}", " ", html)
    text = html.strip()
    text = text.replace("\u3000", " ").replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return text[:10000]

def main():
    set_status("RUNNING")
    findings = []
    scraped = 0

    urls = build_search_urls(QUERY, MAX_PAGES)
    log("Search: " + str(urls))

    for url in urls:
        log("Fetching: " + url)
        content, final_url = fetch(url)
        if content:
            text = extract_text(content)
            findings.append("## 来源: " + final_url + "\n\n" + text + "\n")
            scraped += 1
            log("OK: " + str(len(text)) + " chars")
        else:
            findings.append("## 来源: " + url + "\n失败: " + str(final_url) + "\n")
            log("FAIL: " + str(final_url))
        time.sleep(1)

    result_data = {
        "findings": "\n\n---\n\n".join(findings),
        "scraped_count": scraped,
        "files": [],
    }

    Path(RESULT_PATH).write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
    set_status("DONE")
    log("SAVED: " + RESULT_PATH)

if __name__ == '__main__':
    main()