"""Fix flattened DataLakeWriter and path references in pipeline scripts."""
import re

# Map of file -> (old_pattern, new_line)
FIXES = {
    "scripts/pipeline/build_master_panel.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/build_event_panel.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/build_premium_decomposition.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/collect_enhanced_features.py": (
        r'writer = DataLakeWriter\(',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/collect_external_features.py": (
        r'writer = DataLakeWriter\(out_dir, formats=args\.format\.split,\s*flat=True\)\(",""',
        '        writer = DataLakeWriter(out_dir, formats=args.format.split(","), flat=True)'
    ),
    "scripts/pipeline/expand_events.py": (
        r'writer = DataLakeWriter\(Path\(args\.out_dir\), formats=\["csv"\]\)',
        '        writer = DataLakeWriter(Path(args.out_dir), formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/extract_vn_macro.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/rss_news_sentiment.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/v2_fallback_collector.py": (
        r'writer = DataLakeWriter\(out_dir, formats=\[\s*,\s*flat=True\)"csv"\]\)',
        '        writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)'
    ),
    "scripts/pipeline/crawl_raw_gold_history.py": (
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
