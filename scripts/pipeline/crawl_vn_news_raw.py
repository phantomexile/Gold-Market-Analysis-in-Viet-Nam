"""Tương thích lệnh cũ; mã chính nằm ở ``scripts/collection/crawl_vn_news_raw.py``."""

from __future__ import annotations

import sys
from pathlib import Path

# Thêm thư mục gốc để tìm package scripts khi chạy bằng đường dẫn file.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts._compat import forward_script

forward_script(__name__, "scripts.collection.crawl_vn_news_raw")
