#!/usr/bin/env python3
"""Execute SQL against MySQL using PyMySQL.

Supports either:
- --query "SELECT ..."
- --file path/to/script.sql

Output is tab-delimited with no headers (similar to mysql --batch --raw --skip-column-names).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymysql


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buff: list[str] = []

    in_single = False
    in_double = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                buff.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if not (in_single or in_double or in_backtick):
            if ch == "-" and nxt == "-":
                prev = sql[i - 1] if i > 0 else "\n"
                nxt2 = sql[i + 2] if i + 2 < n else "\n"
                if prev in " \t\r\n" and nxt2 in " \t\r\n":
                    in_line_comment = True
                    i += 2
                    continue
            if ch == "#":
                in_line_comment = True
                i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

        if ch == "'" and not (in_double or in_backtick):
            if in_single and nxt == "'":
                buff.append(ch)
                buff.append(nxt)
                i += 2
                continue
            in_single = not in_single
            buff.append(ch)
            i += 1
            continue

        if ch == '"' and not (in_single or in_backtick):
            in_double = not in_double
            buff.append(ch)
            i += 1
            continue

        if ch == "`" and not (in_single or in_double):
            in_backtick = not in_backtick
            buff.append(ch)
            i += 1
            continue

        if ch == ";" and not (in_single or in_double or in_backtick):
            stmt = "".join(buff).strip()
            if stmt:
                statements.append(stmt)
            buff = []
            i += 1
            continue

        buff.append(ch)
        i += 1

    tail = "".join(buff).strip()
    if tail:
        statements.append(tail)

    return statements


def print_rows(cursor: pymysql.cursors.Cursor) -> None:
    rows = cursor.fetchall()
    if not rows:
        return
    for row in rows:
        if isinstance(row, dict):
            values = list(row.values())
        else:
            values = list(row)
        out = "\t".join("" if v is None else str(v) for v in values)
        print(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute SQL using PyMySQL")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--query")
    parser.add_argument("--file")

    args = parser.parse_args()

    if not args.query and not args.file:
        parser.error("Either --query or --file is required")

    conn = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
    )

    try:
        with conn.cursor() as cursor:
            if args.query:
                cursor.execute(args.query)
                if cursor.description:
                    print_rows(cursor)
                return 0

            sql_path = Path(args.file)
            sql_text = sql_path.read_text(encoding="utf-8")
            statements = split_sql_statements(sql_text)
            for stmt in statements:
                cursor.execute(stmt)
                if cursor.description:
                    _ = cursor.fetchall()
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
