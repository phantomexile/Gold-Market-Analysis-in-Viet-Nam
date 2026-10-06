import urllib.request
import re
import json
import sys

# Try direct Semantic Scholar API with just the ID
paper_id = "21e265cbe93a65f820226c1d0e8b3710faacca00"
url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"

req = urllib.request.Request(url, headers={
    "User-Agent": "ResearchBot/1.0 (mailto:researcher@example.com)",
    "Accept": "application/json"
})

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
        print(json.dumps(data, indent=2, ensure_ascii=False))
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode()[:500]}")
except Exception as e:
    print(f"Error: {e}")
