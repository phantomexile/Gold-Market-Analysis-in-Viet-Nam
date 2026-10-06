"""Scan Claude Code session transcripts and extract read-only tool-call frequencies.
Outputs JSON for allowlist generation.
"""
import json, os, re, collections
from pathlib import Path

PROJECT_DIR = Path.home() / '.claude' / 'projects'
# Gather all .jsonl files across all projects, sorted by mtime desc
files = sorted(PROJECT_DIR.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:50]

bash_counts = collections.Counter()
mcp_counts = collections.Counter()

# Read truncated to avoid loading multi-MB files fully
MAX_BYTES = 5_000_000  # ~5 MB per file tail

for filepath in files:
    try:
        size = filepath.stat().st_size
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            if size > MAX_BYTES:
                fh.seek(max(0, size - MAX_BYTES))
                fh.readline()  # skip partial line
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                if obj.get('type') != 'assistant':
                    continue

                blocks = obj.get('message', {}).get('content', [])
                for block in blocks:
                    if block.get('type') != 'tool_use':
                        continue
                    name = block.get('name', '')

                    if name == 'Bash':
                        cmd = block.get('input', {}).get('command', '') or ''
                        # Handle env-var prefixes and sudo/timeout
                        cmd = cmd.strip()
                        # Remove shell assignment prefix like FOO=bar cmd
                        cmd = re.sub(r'^(\w+=\S+\s+)+', '', cmd)
                        cmd = re.sub(r'^(sudo|timeout)\s+', '', cmd)
                        # Strip leading description after # if present
                        cmd = cmd.split('#')[0].strip()
                        # Tokenize: skip pipes for counting main command
                        main = cmd.split('|')[0].strip().split('&&')[0].strip()
                        tokens = main.split()
                        if not tokens:
                            continue
                        cmd_name = tokens[0]
                        # Subcommand if present (not a flag)
                        if len(tokens) > 1 and not tokens[1].startswith('-'):
                            cmd_name = f'{cmd_name} {tokens[1]}'
                        bash_counts[cmd_name] += 1

                    elif name.startswith('mcp__'):
                        mcp_counts[name] += 1
    except Exception as e:
        print(f'ERROR {filepath}: {e}')

print('=== TOP BASH COMMANDS ===')
for cmd, cnt in bash_counts.most_common(50):
    print(f'{cnt:4d}  {cmd}')

print()
print('=== TOP MCP TOOLS ===')
for tool, cnt in mcp_counts.most_common(30):
    print(f'{cnt:4d}  {tool}')
