"""Test the research script directly"""
import asyncio
import json
import tempfile
from pathlib import Path
from playwright.async_api import async_playwright
import urllib.parse

output_dir = Path(tempfile.mkdtemp(prefix="xrz_test_"))
output_dir.mkdir(exist_ok=True)
print(f"Output dir: {output_dir}")

queries = ["MCP协议 Model Context Protocol"]
max_pages = 5

async def scrape_one(page, url, idx, out_dir):
    result = {"idx": idx, "url": url, "success": False, "text": "", "title": "", "screenshot": ""}
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        shot = out_dir / f"page_{idx}.png"
        await page.screenshot(path=str(shot), full_page=True)
        result["screenshot"] = str(shot)
        try:
            text = await page.evaluate(
                "() => { const b = document.querySelector('body'); return b ? b.innerText.slice(0,5000) : ''; }"
            )
            result["text"] = text[:3000]
        except:
            pass
        try:
            result["title"] = await page.title()
        except:
            pass
        result["success"] = True
        print(f"OK {idx}: {url[:60]}")
    except Exception as e:
        result["error"] = str(e)[:200]
        print(f"FAIL {idx}: {str(e)[:100]}")
    return result

async def main():
    search_urls = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for q in queries[:5]:
            encoded = urllib.parse.quote(q)
            url = "https://www.bing.com/search?q=" + encoded
            print(f"搜索: {q}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                # 截图
                shot = output_dir / f"search_{q[:10]}.png"
                await page.screenshot(path=str(shot), full_page=True)
                # 提取链接 - 尝试多种选择器
                links = []
                for sel in [
                    # Bing 搜索结果
                    """() => {
                        const u = new Set();
                        document.querySelectorAll('h2 a').forEach(a => {
                            const h = a.href;
                            if (h && !h.includes('bing.com') && h.startsWith('http')
                                && !h.includes('microsoft') && !h.includes('github.com/Claude'))
                                u.add(h);
                        });
                        return [...u].slice(0, 12);
                    }""",
                    # Fallback: all links in results area
                    """() => {
                        const u = new Set();
                        document.querySelectorAll('a[href]').forEach(a => {
                            const h = a.href;
                            if (h && h.startsWith('http') && !h.includes('bing.com') 
                                && !h.includes('microsoft.com') && h.length > 20)
                                u.add(h);
                        });
                        return [...u].slice(0, 12);
                    }""",
                ]:
                    try:
                        links = await page.evaluate(sel)
                        if links:
                            print(f"  选择器找到 {len(links)} 个链接")
                            break
                    except Exception as e:
                        print(f"  选择器失败: {e}")
                
                for l in links:
                    search_urls.append({"url": l, "query": q})
                print(f"  找到 {len(links)} 个链接")
            except Exception as e:
                print(f"  搜索失败: {e}")
            await asyncio.sleep(1)
        await browser.close()

    print(f"\n共收集到 {len(search_urls)} 个待爬取页面")
    
    if not search_urls:
        print("没有找到任何链接！Bing搜索可能失败")
        # Save screenshot for debugging
        print(f"截图保存在: {output_dir}")
        return

    # Phase 2: 爬取
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        target = min(len(search_urls), max_pages)
        for i in range(target):
            item = search_urls[i]
            print(f"爬取 {i+1}/{target}: {item['url'][:60]}")
            r = await scrape_one(page, item["url"], i, output_dir)
            r["query"] = item.get("query", "")
            results.append(r)
            await asyncio.sleep(1)
        await browser.close()

    data_path = output_dir / "scraped_data.json"
    data_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成，共 {len(results)} 个页面，成功 {sum(1 for x in results if x.get('success'))} 个")
    print(f"数据已保存: {data_path}")

asyncio.run(main())
