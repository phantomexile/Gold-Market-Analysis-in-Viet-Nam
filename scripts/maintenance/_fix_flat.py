"""Fix flattened DataLakeWriter and path references in pipeline scripts."""

# Tìm thư mục dự án khi chạy trực tiếp; các nhóm script đều nằm cùng độ sâu.
import sys as _sys
from pathlib import Path as _Path

if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from scripts._bootstrap import bootstrap as _bootstrap_project

_bootstrap_project()

import re

# Map of file -> (old_pattern, new_line)
FIXES = {
    "scripts/processing/build_master_panel.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/processing/build_event_panel.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/processing/build_premium_decomposition.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/collection/collect_enhanced_features.py": (
        r'writer = DataLakeWriter\(',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/collection/collect_external_features.py": (
        r'writer = DataLakeWriter\(out_dir, formats=args\.format\.split,\s*flat=True\)\(",""',
        '        writer = DataLakeWriter(out_dir, formats=args.format.split(","), flat=True)'
    ),
    "scripts/processing/expand_events.py": (
        r'writer = DataLakeWriter\(Path\(args\.out_dir\), formats=\["csv"\]\)',
        '        writer = DataLakeWriter(Path(args.out_dir), formats=["csv"], flat=True)'
    ),
    "scripts/processing/extract_vn_macro.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/collection/rss_news_sentiment.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/collection/v2_fallback_collector.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/collection/crawl_raw_gold_history.py": (
        r'writer = DataLakeWriter\(out_dir, formats=output_formats\)',
        '        writer = DataLakeWriter(out_dir, formats=output_formats, flat=True)'
    ),
}

# Also fix: norm = out_dir / "normalized" -> not needed with flat=True
# But keep it if script uses norm variable for output path

for fpath, (pattern, replacement) in FIXES.items():
    with open(fpath, "r", encoding="utf-8") as fh:
        content = fh.read()

    # Try regex substitution first
    new_content, count = re.subn(pattern, replacement, content)

    if count > 0:
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        print(f"Fixed ({count} match(es)): {fpath}")
    else:
        # Try literal match instead
        if pattern in content:
            new_content = content.replace(pattern, replacement)
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            print(f"Fixed (literal): {fpath}")
        else:
            print(f"No match found in: {fpath}")
            # Show what's actually there
            for i, line in enumerate(content.split('\n'), 1):
                if 'DataLakeWriter' in line:
                    print(f"  line {i}: {line.rstrip()}")
