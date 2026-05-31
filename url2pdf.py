#!/usr/bin/env python3
"""
url2pdf.py - 将 URL 或 HTML 转 PDF 并自动上传到 DeepSeek

用法:
  python url2pdf.py <url> [输出文件]
  python url2pdf.py --html "<html内容>" [输出文件]
"""
import sys
import json
import subprocess
import tempfile
import os
from pathlib import Path

WKHTMLTOPDF = r"D:\软件\wkhtmltopdf\bin\wkhtmltopdf.exe"
OUTPUT_DIR = Path.home() / "XianRenZhang_tasks" / "pdf_cache"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_url(url: str) -> tuple:
    """获取网页内容"""
    import urllib.request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.geturl()
    except Exception as e:
        return None, str(e)


def html_to_pdf(html_content: str, output_path: str) -> bool:
    """使用 wkhtmltopdf 将 HTML 转换为 PDF"""
    if not Path(WKHTMLTOPDF).exists():
        print(f"[错误] wkhtmltopdf 不存在: {WKHTMLTOPDF}")
        return False
    
    # 创建临时 HTML 文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
        f.write(html_content)
        temp_html = f.name
    
    try:
        result = subprocess.run(
            [WKHTMLTOPDF, "--enable-local-file-access", temp_html, output_path],
            capture_output=True, timeout=60
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[错误] PDF 转换失败: {e}")
        return False
    finally:
        try:
            os.unlink(temp_html)
        except:
            pass


def url_to_pdf(url: str, output_path: str = None) -> str:
    """将 URL 转换为 PDF"""
    if not output_path:
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        output_path = str(OUTPUT_DIR / f"url_{url_hash}.pdf")
    
    print(f"[转换] 正在获取: {url}")
    html, final_url = fetch_url(url)
    if not html:
        return None
    
    print(f"[转换] 正在生成 PDF: {output_path}")
    if html_to_pdf(html, output_path):
        return output_path
    return None


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python url2pdf.py <url> [输出文件]")
        print("  python url2pdf.py --html '<html>' [输出文件]")
        sys.exit(1)
    
    # 设置输出编码
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    
    arg1 = sys.argv[1]
    
    if arg1 == "--html":
        html_content = sys.argv[2] if len(sys.argv) > 2 else ""
        output_path = sys.argv[3] if len(sys.argv) > 3 else ""
        if not output_path:
            output_path = str(OUTPUT_DIR / "content.pdf")
        print(f"[转换] 正在生成 PDF...")
        if html_to_pdf(html_content, output_path):
            print(f"[完成] PDF 已保存: {output_path}")
        else:
            print(f"[失败] PDF 生成失败")
            sys.exit(1)
    else:
        url = arg1
        output_path = sys.argv[2] if len(sys.argv) > 2 else ""
        
        result = url_to_pdf(url, output_path)
        if result:
            print(f"[完成] PDF 已保存: {result}")
        else:
            print(f"[失败] URL 转 PDF 失败")
            sys.exit(1)


if __name__ == "__main__":
    main()