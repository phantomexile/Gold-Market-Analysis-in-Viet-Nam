import urllib.request
import re
import json

# Try fetching the Semantic Scholar page and extracting embedded data
url = "https://www.semanticscholar.org/paper/21e265cbe93a65f820226c1d0e8b3710faacca00"

req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml",
    "Accept-Language": "en-US,en;q=0.9",
})

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode('utf-8', errors='replace')
        print(f"Page size: {len(html)} bytes")

        # Extract title
        title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE|re.DOTALL)
        if title_m:
            print(f"PAGE TITLE: {title_m.group(1).strip()[:500]}")

        # Look for JSON embedded data (common in SPA pages)
        # Search for paper data in script tags
        script_matches = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
        for s in script_matches[:3]:
            print(f"SCRIPT JSON: {s[:500]}")

        # Look for __NEXT_DATA__ pattern (Next.js)
        next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if next_data:
            print(f"NEXT DATA (first 2000): {next_data.group(1)[:2000]}")

        # Look for any JSON blob with paper info
        json_blobs = re.findall(r'\{[^{}]*"paperId"[^{}]*\}', html[:5000])
        for jb in json_blobs[:3]:
            print(f"JSON BLOB: {jb[:300]}")

        # Search for the paper title in the HTML
        if 'Hedge' in html and 'Safe Haven' in html:
            idx = html.find('Hedge')
            print(f"HTML SNIPPET around 'Hedge': {html[max(0,idx-200):idx+500]}")

        # Search for abstract
        for keyword in ['abstract', 'Abstract', 'ABSTRACTS']:
            indices = [m.start() for m in re.finditer(keyword, html)]
            for idx in indices[:2]:
                snippet = html[max(0,idx-100):idx+800]
                clean = re.sub(r'<[^>]+>', ' ', snippet).strip()
                print(f"ABSTRACT SNIPPET [{keyword} at {idx}]: {clean[:400]}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
