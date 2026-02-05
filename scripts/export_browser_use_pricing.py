from __future__ import annotations

import argparse
import json
from pathlib import Path


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[1]


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Export browser_use TokenCost pricing (CUSTOM_MODEL_PRICING) to a local json file.",
	)
	parser.add_argument(
		"--output",
		default=str(_repo_root() / "pricing" / "token_cost_pricing.json"),
		help="Output json path (default: pricing/token_cost_pricing.json)",
	)
	parser.add_argument(
		"--require-model",
		default="bu-2-0",
		help="Fail if this model key is missing in CUSTOM_MODEL_PRICING (default: bu-2-0)",
	)
	args = parser.parse_args()

	from browser_use.tokens.custom_pricing import CUSTOM_MODEL_PRICING  # noqa: PLC0415

	pricing = dict(CUSTOM_MODEL_PRICING)

	require_model = (args.require_model or "").strip()
	if require_model and require_model not in pricing:
		raise SystemExit(
			f"Model '{require_model}' not found in browser_use.tokens.custom_pricing.CUSTOM_MODEL_PRICING.\n"
			"You're likely using a different Python environment than the crawler runtime.\n"
			"Try running with your conda env python, e.g.:\n"
			"  C:\\Users\\yaowu\\miniconda3\\envs\\shangji\\python.exe scripts\\export_browser_use_pricing.py"
		)

	out_path = Path(args.output)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(
		json.dumps(pricing, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
		encoding="utf-8",
	)
	print(f"Wrote {out_path} ({len(pricing)} models)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

