from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _safe_stdout_utf8() -> None:
	try:
		sys.stdout.reconfigure(encoding="utf-8")
	except Exception:
		pass


def _read_file_text(path: str) -> str:
	p = Path(path)
	if not p.exists():
		raise FileNotFoundError(path)

	# Try common encodings (UTF-8 first, then Windows-friendly fallback).
	for enc in ("utf-8-sig", "utf-8", "gb18030"):
		try:
			t = p.read_text(encoding=enc)
			return t.lstrip("\ufeff")
		except UnicodeDecodeError:
			continue
	return p.read_text(encoding="utf-8", errors="replace")


def _read_input_text(file: str | None) -> str:
	if file:
		return _read_file_text(file)

	if sys.stdin is None:
		return ""

	# If stdin is piped, read bytes and decode with a small heuristic.
	# This avoids common Windows PowerShell pipeline encoding issues (often UTF-16LE).
	if not sys.stdin.isatty():
		try:
			data = sys.stdin.buffer.read()
		except Exception:
			return sys.stdin.read()

		if not data:
			return ""

		# BOM / heuristic first.
		if data.startswith(b"\xef\xbb\xbf"):
			return data.decode("utf-8-sig")
		if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
			return data.decode("utf-16")
		if b"\x00" in data[:200]:
			for enc in ("utf-16", "utf-16-le", "utf-16-be"):
				try:
					return data.decode(enc)
				except Exception:
					continue

		# Common encodings.
		for enc in ("utf-8", "gb18030"):
			try:
				return data.decode(enc)
			except Exception:
				continue
		return data.decode("utf-8", errors="replace")

	# Interactive stdin: read line-by-line and stop as soon as we have valid JSON.
	sys.stderr.write("Paste JSON, then press Enter. The script will output as soon as JSON is complete.\n")
	lines: list[str] = []
	while True:
		try:
			line = input()
		except EOFError:
			break

		lines.append(line)
		text = "\n".join(lines).strip()
		if not text:
			continue

		try:
			json.loads(text)
			return text
		except json.JSONDecodeError:
			# Keep reading until JSON becomes valid.
			continue

	return "\n".join(lines)


def _json_loads_maybe_twice(text: str):
	obj = json.loads(text)
	if isinstance(obj, str):
		# Some tools may export JSON as a JSON-string (e.g. "\"{...}\"").
		try:
			return json.loads(obj)
		except Exception:
			return obj
	return obj


def main() -> int:
	_safe_stdout_utf8()

	parser = argparse.ArgumentParser(
		description=(
			"Wrap a raw JSON object into a Postman-ready request body for /normalize_item.\n"
			"Output format: {\"sourceJson\": \"<JSON string>\"}\n\n"
			"Examples:\n"
			"  python scripts/wrap_source_json.py --file item.json\n"
			"  Get-Content item.json -Raw | python scripts/wrap_source_json.py\n"
		),
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	parser.add_argument("--file", default=None, help="Input JSON file (default: read from stdin)")
	parser.add_argument("--out", default=None, help="Write output JSON to file (default: print to stdout)")
	parser.add_argument("--key", default="sourceJson", help="Wrapper field name (default: sourceJson)")
	parser.add_argument("--pretty", action="store_true", help="Pretty-print outer JSON (indent=2)")
	parser.add_argument(
		"--pretty-inner",
		action="store_true",
		help="Pretty-print inner JSON string (bigger, but easier to read)",
	)
	args = parser.parse_args()

	raw = _read_input_text(args.file).strip()
	if not raw:
		print('{"%s": ""}' % args.key)
		return 0

	try:
		parsed = _json_loads_maybe_twice(raw)
	except json.JSONDecodeError as e:
		sys.stderr.write(f"Invalid JSON input: {e}\n")
		sys.stderr.write("Tip: if you copied from logs, make sure the input is valid JSON.\n")
		return 2

	# If the input already looks like {"sourceJson": "..."} keep it, just reformat.
	if isinstance(parsed, dict) and list(parsed.keys()) == [args.key] and isinstance(parsed.get(args.key), str):
		out_obj = parsed
	else:
		inner = (
			json.dumps(parsed, ensure_ascii=False, indent=2)
			if args.pretty_inner
			else json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
		)
		out_obj = {args.key: inner}

	out_text = json.dumps(out_obj, ensure_ascii=False, indent=2 if args.pretty else None)

	if args.out:
		Path(args.out).write_text(out_text, encoding="utf-8")
	else:
		print(out_text)

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
