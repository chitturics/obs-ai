"""
CLI wrapper around the search optimization service logic.
"""
import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root
from containers.search_opt.core import handle_query


def main():
    parser = argparse.ArgumentParser(description="SPL/NLP query review container CLI")
    parser.add_argument("--sql_query", required=True, help="Input query (SPL or natural language)")
    parser.add_argument("--type", choices=["nlp", "spl"], required=True, help="Interpretation of input")
    parser.add_argument("--action", choices=["review", "optimize", "improve", "learn"], required=True)
    parser.add_argument("--store", default="data/spl_best_practices.json",
                        help="Path to store learned best practices (when action=learn)")
    args = parser.parse_args()

    result = handle_query(args.sql_query, args.type, args.action, store_path=Path(args.store))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
