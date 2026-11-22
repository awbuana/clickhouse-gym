#!/usr/bin/env python3
"""ClickHouse gym: an interactive shell to practise SQL for the ClickHouse
Certified Developer exam, using the Real-Time Analytics course datasets.

You write the SQL; the gym runs it on your ClickHouse and checks it:
  * query exercises compare your result with the reference result
  * DDL / DML exercises inspect system tables and data afterwards

Usage
  python3 gym/gym.py              start the shell
  python3 gym/gym.py --setup      (re)load the gym database
  python3 gym/gym.py --selftest   run every reference solution through the checker
  python3 gym/gym.py --topic=V,D  start focused on some topics (letters from \\focus)

Connection (env vars): CH_HOST=localhost CH_PORT=8123 CH_USER=default CH_PASSWORD=clickhouse
"""

import json
import os
import random
import re
import sys
import textwrap
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exercises as bank  # noqa: E402

try:
    import readline
except ImportError:  # pragma: no cover
    readline = None

HOST = os.environ.get("CH_HOST", "localhost")
PORT = os.environ.get("CH_PORT", "8123")
USER = os.environ.get("CH_USER", "default")
PASSWORD = os.environ.get("CH_PASSWORD", "clickhouse")
DB = bank.DB

STATE_DIR = os.path.expanduser("~/.clickhouse_gym")
PROGRESS_FILE = os.path.join(STATE_DIR, "progress.json")
HISTORY_FILE = os.path.join(STATE_DIR, "history")

EXERCISES = bank.EXERCISES
BY_ID = {e["id"].upper(): e for e in EXERCISES}
SECTION_NAMES = dict(bank.SECTIONS)

# ---------------------------------------------------------------- colours

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code):
    return (lambda s: f"\033[{code}m{s}\033[0m") if _COLOR else (lambda s: s)


bold, dim, red, green, yellow, cyan = _c("1"), _c("2"), _c("31"), _c("32"), _c("33"), _c("36")


def _rl(s):
    """Wrap ANSI codes for readline prompts so line editing stays aligned."""
    return re.sub(r"(\033\[[0-9;]*m)", "\001\\1\002", s) if readline else s


# ---------------------------------------------------------------- ClickHouse

class CHError(Exception):
    pass


def clean_error(text):
    text = text.strip()
    first = text.split("\n")[0]
    first = re.sub(r"\s*\(version [^)]*\)\s*$", "", first)
    first = re.sub(r"\.?\s*Stack trace.*$", "", first)
    return first[:700] + ("…" if len(first) > 700 else "")


GYM_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(GYM_DIR)
INFILE_RE = re.compile(
    r"^(?P<head>INSERT\s+INTO\s+.+?)\s+FROM\s+INFILE\s+'(?P<path>[^']+)'"
    r"(?:\s+COMPRESSION\s+'(?P<comp>[^']*)')?(?:\s+FORMAT\s+(?P<fmt>\w+))?\s*$",
    re.I | re.S)

# Like clickhouse-client: without FORMAT, the format comes from the file extension.
EXT_FORMATS = {".csv": "CSV", ".tsv": "TabSeparated", ".parquet": "Parquet", ".json": "JSONEachRow",
               ".ndjson": "JSONEachRow", ".jsonl": "JSONEachRow", ".orc": "ORC", ".avro": "Avro",
               ".arrow": "Arrow"}


def resolve_path(path):
    if os.path.isabs(path):
        return path
    for base in (os.getcwd(), REPO_DIR, GYM_DIR):
        candidate = os.path.join(base, path)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(os.getcwd(), path)


def execute(stmt):
    """Run a statement like clickhouse-client would, including INSERT ... FROM INFILE."""
    m = INFILE_RE.match(strip_comments(stmt))
    if m:
        if m.group("comp") and m.group("comp").lower() not in ("none", "auto"):
            raise CHError("The gym supports FROM INFILE without COMPRESSION only.")
        path = resolve_path(m.group("path"))
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError as e:
            raise CHError(f"Cannot read {m.group('path')}: {e.strerror}")
        fmt = m.group("fmt") or EXT_FORMATS.get(os.path.splitext(path)[1].lower())
        if not fmt:
            raise CHError(f"Can't tell the format of {m.group('path')} from its extension. Add FORMAT <name>.")
        return run(f"{m.group('head')} FORMAT {fmt}", body=body)
    return run(stmt)


def run(sql, database=DB, timeout=900, body=None, raw=False, query_id=None):
    """Run one statement. Returns parsed JSONCompact dict, raw text, or None.
    With body, the SQL goes in the URL and body is the INSERT data."""
    params = {
        "wait_end_of_query": "1",
        "default_format": "JSONCompact",
        "output_format_json_quote_64bit_integers": "0",
        "output_format_json_quote_decimals": "0",
    }
    if database:
        params["database"] = database
    if body is not None:
        params["query"] = sql
    if query_id:
        params["query_id"] = query_id
    url = f"http://{HOST}:{PORT}/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=body if body is not None else sql.encode(), headers={
        "X-ClickHouse-User": USER, "X-ClickHouse-Key": PASSWORD})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            if raw:
                return payload
            body = payload.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise CHError(clean_error(e.read().decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise CHError(f"Cannot reach ClickHouse at {HOST}:{PORT} ({e.reason}). Is it running? Try: make up")
    if not body.strip():
        return None
    try:
        data = json.loads(body)
        if isinstance(data, dict) and "data" in data:
            return data
    except ValueError:
        pass
    return body


def scalar(sql, database=DB):
    res = run(sql, database)
    if isinstance(res, dict) and res["data"]:
        return res["data"][0][0]
    return None


def split_sql(text):
    """Split on top-level semicolons. Returns (statements, remainder)."""
    stmts, buf, i, n = [], [], 0, len(text)
    quote = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if quote:
            buf.append(ch)
            if ch == "\\" and quote in "'\"":
                if nxt:
                    buf.append(nxt)
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
            buf.append(ch)
        elif ch == "-" and nxt == "-":
            j = text.find("\n", i)
            j = n if j == -1 else j
            buf.append(text[i:j])
            i = j
            continue
        elif ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            buf.append(text[i:j])
            i = j
            continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if strip_comments(stmt):
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    return stmts, "".join(buf)


def strip_comments(s):
    s = re.sub(r"--[^\n]*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s.strip()


# ---------------------------------------------------------------- output

def cell_text(v, width=48):
    if v is None:
        s = "NULL"
    elif isinstance(v, (list, dict)):
        s = json.dumps(v, ensure_ascii=False)
    else:
        s = str(v)
    s = s.replace("\n", "↵")
    return s if len(s) <= width else s[: width - 1] + "…"


def render(res, max_rows=25):
    if not isinstance(res, dict):
        print(res.rstrip())
        return
    cols = [m["name"] for m in res["meta"]]
    rows = res["data"]
    if len(rows) == 1 and len(cols) == 1 and isinstance(rows[0][0], str) and "\n" in rows[0][0]:
        print(rows[0][0])  # SHOW CREATE and friends
    else:
        shown = [[cell_text(v) for v in r] for r in rows[:max_rows]]
        heads = [cell_text(c, 40) for c in cols]
        widths = [max([len(h)] + [len(r[i]) for r in shown]) for i, h in enumerate(heads)]
        line = "  ".join(h.ljust(w) for h, w in zip(heads, widths))
        print(bold(line))
        print(dim("  ".join("─" * w for w in widths)))
        for r in shown:
            print("  ".join(c.ljust(w) for c, w in zip(r, widths)))
        if len(rows) > max_rows:
            print(dim(f"… {len(rows) - max_rows} more rows"))
    st = res.get("statistics") or {}
    bits = [f"{len(rows)} row{'s' if len(rows) != 1 else ''}"]
    if "elapsed" in st:
        bits.append(f"{st['elapsed']:.3f}s")
    if st.get("rows_read"):
        bits.append(f"read {human(st['rows_read'])} rows")
    print(dim(" · ".join(bits)))


def human(n):
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= size:
            return f"{n / size:.2f}{unit}"
    return str(n)


# ---------------------------------------------------------------- checking

def norm(v, sets=False):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:
            return "nan"
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.6g}"
    if isinstance(v, list):
        items = [norm(x, sets) for x in v]
        return "[" + ",".join(sorted(items) if sets else items) + "]"
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True)
    return str(v)


def compare(user, ref, ordered, sets=False):
    """Return (ok, explanation)."""
    if not isinstance(user, dict):
        return False, "No table result to compare. Run a SELECT without a FORMAT clause."
    uc, rc = len(user["meta"]), len(ref["meta"])
    U = [tuple(norm(v, sets) for v in r) for r in user["data"]]
    R = [tuple(norm(v, sets) for v in r) for r in ref["data"]]
    if uc != rc:
        return False, f"Expected {rc} column{'s' if rc != 1 else ''}, you returned {uc}."
    if ordered:
        if U == R:
            return True, ""
        if Counter(U) == Counter(R):
            return False, "Right rows, wrong order. Check your ORDER BY."
    elif Counter(U) == Counter(R):
        return True, ""
    msg = [f"Expected {len(R)} row{'s' if len(R) != 1 else ''}, you returned {len(U)}."
           if len(R) != len(U) else "Same number of rows, but the values differ."]
    missing = list((Counter(R) - Counter(U)).elements())[:3]
    extra = list((Counter(U) - Counter(R)).elements())[:3]
    if missing:
        msg.append("Expected but missing: " + "; ".join("(" + ", ".join(cell_text(c, 30) for c in r) + ")" for r in missing))
    if extra:
        msg.append("You returned extra:   " + "; ".join("(" + ", ".join(cell_text(c, 30) for c in r) + ")" for r in extra))
    if ordered and not missing and not extra:
        msg.append("Row order differs.")
    return False, "\n".join(msg)


def run_setup(ex):
    for step in ex["setup"]:
        if isinstance(step, tuple):
            kind = step[0]
            if kind == "if_empty":
                _, table, stmt = step
                if int(scalar(f"SELECT count() FROM {table}") or 0) == 0:
                    run(stmt)
            elif kind == "file":
                _, rel, stmt = step
                path = os.path.join(REPO_DIR, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(run(stmt, raw=True))
            elif kind == "if_empty_where":
                _, table, where, stmt = step
                if int(scalar(f"SELECT count() FROM {table} WHERE {where}") or 0) == 0:
                    run(stmt)
        else:
            run(step)


def reference_result(ex):
    stmts, rest = split_sql(ex["solution"] + ";")
    res = None
    for s in stmts:
        res = execute(s)
    return res


def verify(ex, last_result, retries=3):
    """Return (ok, list_of_messages)."""
    if ex["check"] == "result":
        if last_result is None:
            return False, ["Nothing to compare yet: your last statement returned no rows/columns."]
        ok, why = compare(last_result, reference_result(ex), ex["ordered"], ex.get("sets", False))
        return ok, [why] if why else []
    for attempt in range(retries):
        failures = []
        for check_sql, message in ex["check"]:
            try:
                value = scalar(check_sql)
            except CHError as e:
                value = None
                message = f"{message}  ({e})"
            if value not in (1, True, "1"):
                failures.append(message)
        if not failures:
            return True, []
        if attempt < retries - 1:
            time.sleep(1.5)  # refreshes / mutations can finish a moment later
    return False, failures


# ---------------------------------------------------------------- progress

def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_progress(p):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(PROGRESS_FILE, "w") as f:
            json.dump(p, f, indent=1)
    except OSError:
        pass


def status_mark(p):
    if not p:
        return dim("·")
    if p.get("last") == "pass":
        return green("✓")
    if p.get("revealed") and p.get("last") != "pass":
        return yellow("?")
    return red("✗")


def priority(p):
    """Higher = more practice needed (simple spaced repetition)."""
    if not p:
        return 5
    if p.get("last") != "pass":
        return 5 if p.get("revealed") else 4
    return max(1, 3 - p.get("streak", 0))


# ---------------------------------------------------------------- data setup

def ensure_database(interactive=True, force=False):
    run(f"CREATE DATABASE IF NOT EXISTS {DB}", database=None)
    rows = int(scalar(f"SELECT count() FROM system.tables WHERE database = '{DB}' AND name = 'uk_prices_3'", None) or 0)
    if rows and not force:
        count = int(scalar("SELECT count() FROM uk_prices_3") or 0)
        if count > 0:
            return True
    if interactive and not force:
        print(yellow("The gym database has no uk_prices_3 data yet."))
        if input("Load it now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            return False
    run(f"DROP DATABASE IF EXISTS {DB}", database=None)
    run(f"CREATE DATABASE {DB}", database=None)
    run(bank.BASE_TABLE, database=None)
    t0 = time.time()
    print("Loading ~30M rows from the course S3 file into gym.uk_prices_3 (a few minutes) …")
    print(dim("  " + bank.PRICES_URL))
    load_with_progress(bank.LOAD_FROM_S3)
    print(green(f"Loaded {human(int(scalar('SELECT count() FROM uk_prices_3')))} rows in {time.time() - t0:.0f}s."))
    return True


def load_with_progress(sql, expected_rows=30_033_199):
    """Run a long INSERT, printing server-side progress; Ctrl-C cancels it on the server."""
    # A previous setup that was interrupted may still be running on the server.
    run("KILL QUERY WHERE query_id LIKE 'gym-setup-%' SYNC", database=None)
    qid = f"gym-setup-{uuid.uuid4().hex[:8]}"
    outcome = {}

    def worker():
        try:
            run(sql, database=None, timeout=3600, query_id=qid)
        except CHError as e:
            outcome["error"] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(2)
            try:
                res = run(f"SELECT read_rows, read_bytes, elapsed FROM system.processes WHERE query_id = '{qid}'",
                          database=None, timeout=10)
            except CHError:
                continue
            if isinstance(res, dict) and res["data"]:
                rows, size, secs = res["data"][0]
                pct = min(100, 100 * rows / expected_rows)
                sys.stdout.write(f"\r  {pct:5.1f}%  {human(rows)} rows · {size / 2**20:,.0f} MiB downloaded · {secs:.0f}s   ")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print(yellow("\nCancelling the load on the server …"))
        run(f"KILL QUERY WHERE query_id = '{qid}' SYNC", database=None)
        raise
    print()
    if "error" in outcome:
        raise outcome["error"]


# ---------------------------------------------------------------- shell

HELP = f"""
{bold('Write SQL')} ending with ; and press Enter. Multi-line is fine; several statements too.
Your attempt is checked automatically. Prefix with {cyan('?')} to run SQL without checking.

{bold('Commands')}
  {cyan(chr(92) + 'l')} [section|all] list exercises (✓ passed, ✗ failed, ? solution seen, · new)
  {cyan(chr(92) + 'g')} <id>          go to an exercise, e.g. \\g Q5
  {cyan(chr(92) + 'n')} / {cyan(chr(92) + 'p')}         next / previous exercise
  {cyan(chr(92) + 't')}               show the task again
  {cyan(chr(92) + 'h')}               next hint
  {cyan(chr(92) + 's')}               show the solution (counts as not solved)
  {cyan(chr(92) + 'r')}               reset the exercise (re-runs its setup)
  {cyan(chr(92) + 'focus')} [letters]  practise only some topics, e.g. \\focus V D  (\\focus all clears)
  {cyan(chr(92) + 'drill')}           spaced repetition: picks what you know least
  {cyan(chr(92) + 'exam')} [n] [min]  timed mock: n random exercises, no hints (default 12, 60)
  {cyan(chr(92) + 'practice')}        back to normal mode
  {cyan(chr(92) + 'stats')}           progress per section
  {cyan(chr(92) + 'setup')}           wipe the gym database and reload the data
  {cyan(chr(92) + 'q')}               quit
"""


class Gym:
    def __init__(self):
        self.progress = load_progress()
        self.mode = "practice"
        self.idx = 0
        self.hint_level = 0
        self.exam = None
        self.focus = [c for c in self.progress.get("_focus", []) if c in SECTION_NAMES]
        last = self.progress.get("_last")
        if last and last.upper() in BY_ID:
            self.idx = EXERCISES.index(BY_ID[last.upper()])

    # ---- navigation
    @property
    def ex(self):
        return EXERCISES[self.idx]

    def pool(self):
        """Indices of exercises in the focused topics (all when no focus)."""
        return [i for i, e in enumerate(EXERCISES) if not self.focus or e["section"] in self.focus]

    def step(self, direction):
        pool = self.pool()
        if self.idx in pool:
            pos = (pool.index(self.idx) + direction) % len(pool)
        else:
            later = [i for i in pool if (i > self.idx if direction > 0 else i < self.idx)]
            pos = pool.index(later[0] if direction > 0 and later else later[-1] if later else pool[0])
        self.open(pool[pos])

    def set_focus(self, codes):
        codes = [c.upper() for c in codes]
        if not codes or codes == ["ALL"]:
            self.focus = []
        else:
            bad = [c for c in codes if c not in SECTION_NAMES]
            if bad:
                return print(red(f"Unknown topic {', '.join(bad)}. Use the letters from \\focus."))
            self.focus = [c for c, _ in bank.SECTIONS if c in codes]
        self.progress["_focus"] = self.focus
        save_progress(self.progress)
        if self.focus:
            names = ", ".join(SECTION_NAMES[c] for c in self.focus)
            print(green(f"Focus: {names} ({len(self.pool())} exercises)."),
                  dim("\\n, \\drill and \\exam stay inside these topics. \\focus all to clear."))
            if self.idx not in self.pool():
                self.open(self.pool()[0])
        else:
            print(green(f"Focus cleared: all {len(EXERCISES)} exercises."))

    def focus_menu(self):
        print(bold("\nTopics"))
        for code, name in bank.SECTIONS:
            items = [e for e in EXERCISES if e["section"] == code]
            passed = sum(1 for e in items if (self.progress.get(e["id"]) or {}).get("last") == "pass")
            mark = cyan("●") if code in self.focus else dim("○")
            print(f"  {mark} {bold(code)}  {name:<24} {dim(f'{passed}/{len(items)} passed')}")
        try:
            answer = input("Topics to practise (letters, e.g. 'V D'; blank = all): ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        self.set_focus(re.findall(r"[A-Za-z]+", answer))

    def open(self, idx, quiet=False):
        self.idx = idx % len(EXERCISES)
        self.hint_level = 0
        self.progress["_last"] = self.ex["id"]
        save_progress(self.progress)
        if self.ex["setup"]:
            print(dim("Preparing exercise …"))
            try:
                run_setup(self.ex)
            except CHError as e:
                print(red(f"Setup failed: {e}"))
        if not quiet:
            self.show_task()

    def show_task(self):
        e = self.ex
        p = self.progress.get(e["id"])
        tag = f"[{SECTION_NAMES[e['section']]}]"
        print()
        print(f"{bold(cyan(e['id']))} {bold(e['title'])}  {dim(tag)}  {status_mark(p)}")
        for line in e["task"].split("\n"):
            if line.startswith("  "):
                print("  " + line)
            else:
                print(textwrap.fill(line, 92, initial_indent="  ", subsequent_indent="  ") if line else "")
        kind = "Write a query: your result is compared with the reference." if e["check"] == "result" \
            else "Write the statement(s): the database is inspected afterwards."
        extra = "" if self.exam else dim(f"  \\h hint ({len(e['hints'])})  \\s solution  \\n next")
        print(dim(f"  {kind}"), extra)
        if self.exam:
            left = self.exam["deadline"] - time.time()
            print(yellow(f"  Exam: exercise {self.exam['pos'] + 1}/{len(self.exam['items'])}, {max(0, left) / 60:.1f} min left"))
        print()

    def next(self):
        if self.exam:
            return self.exam_next(skipped=True)
        if self.mode == "drill":
            return self.drill_pick()
        self.step(1)

    def drill_pick(self):
        weights = [priority(self.progress.get(e["id"])) for e in EXERCISES]
        pool = self.pool()
        choices = [i for i in pool if i != self.idx] or pool
        idx = random.choices(choices, weights=[weights[i] ** 2 for i in choices])[0]
        self.open(idx)

    # ---- attempts
    def attempt(self, text, explore=False):
        stmts, _ = split_sql(text if text.rstrip().endswith(";") else text + ";")
        last = None
        error = None
        for s in stmts:
            if len(stmts) > 1:
                print(dim("» " + strip_comments(s).split("\n")[0][:80]))
            try:
                res = execute(s)
            except CHError as e:
                error = str(e)
                print(red(error))
                break
            if res is not None:
                render(res)
                last = res
            elif len(stmts) == 1 or s is stmts[-1]:
                print(dim("OK"))
        if explore:
            return
        e = self.ex
        p = self.progress.setdefault(e["id"], {"attempts": 0, "passes": 0, "streak": 0})
        p["attempts"] += 1
        p["ts"] = int(time.time())
        if error:
            p["last"] = "fail"
            p["streak"] = 0
            save_progress(self.progress)
            print(red("✗ The statement failed. Fix the error and try again."))
            return
        try:
            ok, messages = verify(e, last)
        except CHError as err:
            ok, messages = False, [f"Checker error: {err}"]
        if ok:
            p["passes"] += 1
            p["streak"] = p.get("streak", 0) + 1
            p["last"] = "pass"
            if not p.get("revealed") or p.get("passes", 0) > 1:
                p["revealed"] = False
            save_progress(self.progress)
            print(green(bold("✓ Correct!")) + dim(f"  (passed {p['passes']}×, streak {p['streak']})"))
            if self.exam:
                self.exam["results"][e["id"]] = "pass"
                self.exam_next()
            elif self.mode == "drill":
                self.drill_pick()
            else:
                print(dim("  \\n for the next exercise, \\s to compare with the reference solution."))
        else:
            p["last"] = "fail"
            p["streak"] = 0
            save_progress(self.progress)
            print(red(bold("✗ Not yet.")))
            for m in messages:
                for line in m.split("\n"):
                    print(red("  " + line))

    # ---- hints & solutions
    def hint(self):
        if self.exam:
            return print(yellow("No hints in exam mode."))
        hints = self.ex["hints"]
        if not hints:
            return print(dim("No hints for this one. \\s shows the solution."))
        if self.hint_level >= len(hints):
            return print(dim("No more hints. \\s shows the solution."))
        self.hint_level += 1
        print(yellow(f"Hint {self.hint_level}/{len(hints)}: ") + hints[self.hint_level - 1])

    def solution(self):
        if self.exam:
            return print(yellow("No solutions in exam mode."))
        e = self.ex
        p = self.progress.setdefault(e["id"], {"attempts": 0, "passes": 0, "streak": 0})
        if p.get("last") != "pass":
            p["revealed"] = True
            p["streak"] = 0
        save_progress(self.progress)
        print(dim("── reference solution ──"))
        print(cyan(e["solution"] + ";"))
        print(dim("Retype it from memory later: \\r resets the exercise."))

    # ---- listing
    def list(self, section=None):
        current = None
        wanted = [section.upper()] if section else self.focus
        if wanted and not section:
            print(dim(f"Showing focused topics ({', '.join(self.focus)}). \\l all shows everything."))
        if section and section.lower() == "all":
            wanted = []
        for i, e in enumerate(EXERCISES):
            if wanted and e["section"] not in wanted:
                continue
            if e["section"] != current:
                current = e["section"]
                print(bold(f"\n{current}  {SECTION_NAMES[current]}"))
            here = cyan("▶") if i == self.idx else " "
            print(f" {here} {status_mark(self.progress.get(e['id']))} {e['id']:<4} {e['title']}")
        print()

    def stats(self):
        total_pass = 0
        print()
        for code, name in bank.SECTIONS:
            items = [e for e in EXERCISES if e["section"] == code]
            passed = sum(1 for e in items if (self.progress.get(e["id"]) or {}).get("last") == "pass")
            total_pass += passed
            bar = "█" * passed + "░" * (len(items) - passed)
            mark = cyan("●") if code in self.focus else " "
            print(f" {mark}{code}  {name:<24} {green(bar)} {passed}/{len(items)}")
        weak = sorted((EXERCISES[i] for i in self.pool()), key=lambda e: -priority(self.progress.get(e["id"])))[:5]
        print(f"\n  Total {total_pass}/{len(EXERCISES)} passed.  Practise next: " + ", ".join(e["id"] for e in weak))
        print()

    # ---- exam
    def exam_start(self, n=12, minutes=60):
        pool = self.pool()
        n = max(1, min(n, len(pool)))
        items = random.sample(pool, n)
        self.exam = {"items": items, "pos": 0, "results": {}, "deadline": time.time() + minutes * 60,
                     "start": time.time(), "minutes": minutes}
        scope = ", ".join(SECTION_NAMES[c] for c in self.focus) if self.focus else "all topics"
        print(bold(f"\nExam: {n} exercises from {scope}, {minutes:g} minutes. No hints or solutions. \\n skips."))
        self.open(items[0])

    def exam_next(self, skipped=False):
        ex_ = self.exam
        if skipped:
            ex_["results"].setdefault(self.ex["id"], "skip")
        ex_["pos"] += 1
        if ex_["pos"] >= len(ex_["items"]) or time.time() > ex_["deadline"]:
            return self.exam_finish()
        self.open(ex_["items"][ex_["pos"]])

    def exam_finish(self):
        ex_ = self.exam
        self.exam = None
        ids = [EXERCISES[i]["id"] for i in ex_["items"]]
        passed = [i for i in ids if ex_["results"].get(i) == "pass"]
        mins = (time.time() - ex_["start"]) / 60
        pct = 100 * len(passed) / len(ids)
        print(bold(f"\nExam finished: {len(passed)}/{len(ids)} ({pct:.0f}%) in {mins:.1f} min"))
        for i in ids:
            r = ex_["results"].get(i, "not reached")
            print(f"  {green('✓') if r == 'pass' else red('✗')} {i:<4} {BY_ID[i]['title']}  {dim(r if r != 'pass' else '')}")
        print(dim("Review the misses with \\g <id> and \\s.\n"))

    # ---- main loop
    def prompt(self):
        e = self.ex
        mode = {"practice": "", "drill": "drill "}[self.mode] if not self.exam else "exam "
        focus = f"[{''.join(self.focus)}] " if self.focus else ""
        return _rl(f"{dim(focus + mode)}{cyan(e['id'])}{dim('>')} ")

    def command(self, line):
        parts = line[1:].split()
        cmd, args = (parts[0].lower() if parts else ""), parts[1:]
        if cmd in ("q", "quit", "exit"):
            raise EOFError
        elif cmd in ("help", "?"):
            print(HELP)
        elif cmd == "l":
            self.list(args[0] if args else None)
        elif cmd == "g":
            if not args or args[0].upper() not in BY_ID:
                print(red("Usage: \\g <id>, e.g. \\g Q5 (see \\l)"))
            elif self.exam:
                print(yellow("Finish or quit the exam first (\\practice)."))
            else:
                self.open(EXERCISES.index(BY_ID[args[0].upper()]))
        elif cmd == "n":
            self.next()
        elif cmd == "p":
            if self.exam:
                print(yellow("No going back in exam mode."))
            else:
                self.step(-1)
        elif cmd == "t":
            self.show_task()
        elif cmd == "h":
            self.hint()
        elif cmd == "s":
            self.solution()
        elif cmd == "r":
            self.open(self.idx)
        elif cmd == "drill":
            self.exam = None
            self.mode = "drill"
            print(bold("Drill mode: exercises you know least come up most. \\practice to stop."))
            self.drill_pick()
        elif cmd == "practice":
            if self.exam:
                self.exam_finish()
            self.mode = "practice"
            print("Practice mode.")
        elif cmd == "exam":
            try:
                n = int(args[0]) if args else 12
                m = float(args[1]) if len(args) > 1 else 60
            except ValueError:
                return print(red("Usage: \\exam [count] [minutes]"))
            self.exam_start(n, m)
        elif cmd in ("focus", "topic", "topics"):
            if args:
                self.set_focus(args)
            else:
                self.focus_menu()
        elif cmd == "stats":
            self.stats()
        elif cmd == "setup":
            if input("This drops everything in the gym database. Continue? [y/N] ").strip().lower() in ("y", "yes"):
                ensure_database(interactive=False, force=True)
                self.open(self.idx)
        else:
            print(red(f"Unknown command \\{cmd}. \\help lists commands."))

    def loop(self):
        print(bold("\nClickHouse gym") + dim(f"  ({len(EXERCISES)} exercises · database `{DB}` on {HOST}:{PORT})"))
        print(dim("Type \\help for commands, \\l to list exercises, \\drill or \\exam to train.\n"))
        if self.focus and self.idx not in self.pool():
            self.idx = self.pool()[0]
        if self.focus:
            print(cyan("Focus: " + ", ".join(SECTION_NAMES[c] for c in self.focus)) + dim("  (\\focus to change)"))
        self.open(self.idx)
        buf = []
        while True:
            if self.exam and time.time() > self.exam["deadline"]:
                print(yellow("Time is up."))
                self.exam_finish()
            try:
                line = input(self.prompt() if not buf else _rl(dim("  … ")))
            except KeyboardInterrupt:
                print()
                buf = []
                continue
            if not buf and line.strip().startswith("\\"):
                try:
                    self.command(line.strip())
                except CHError as e:
                    print(red(str(e)))
                continue
            buf.append(line)
            text = "\n".join(buf)
            stmts, rest = split_sql(text)
            if not stmts or strip_comments(rest):
                if not strip_comments(text):
                    buf = []
                continue
            buf = []
            explore = text.lstrip().startswith("?")
            if explore:
                text = text.lstrip()[1:]
            self.attempt(text, explore=explore)


# ---------------------------------------------------------------- self-test

def selftest(ids=None):
    """Run every reference solution through setup + checker."""
    targets = [BY_ID[i.upper()] for i in ids] if ids else EXERCISES
    failed = 0
    for e in targets:
        t0 = time.time()
        try:
            run_setup(e)
            stmts, _ = split_sql(e["solution"] + ";")
            last = None
            for s in stmts:
                res = execute(s)
                if res is not None:
                    last = res
            ok, msgs = verify(e, last)
        except CHError as err:
            ok, msgs = False, [str(err)]
        failed += not ok
        print(f"{green('PASS') if ok else red('FAIL')} {e['id']:<4} {e['title']:<40} {dim(f'{time.time() - t0:.1f}s')}")
        for m in msgs:
            print(red("     " + m))
    print(f"\n{len(targets) - failed}/{len(targets)} passed")
    return failed == 0


def main():
    args = sys.argv[1:]
    try:
        if "--setup" in args:
            try:
                ensure_database(interactive=False, force=True)
            except KeyboardInterrupt:
                print("Setup cancelled. Run `make gym-setup` again to reload.")
            return
        if not ensure_database(interactive="--selftest" not in args):
            return
        if "--selftest" in args:
            ids = [a for a in args if not a.startswith("--")]
            sys.exit(0 if selftest(ids or None) else 1)
    except CHError as e:
        print(red(str(e)))
        sys.exit(1)

    if readline:
        os.makedirs(STATE_DIR, exist_ok=True)
        try:
            readline.read_history_file(HISTORY_FILE)
        except OSError:
            pass
        readline.set_history_length(2000)
    gym = Gym()
    for a in args:
        if a.startswith("--topic=") or a.startswith("--focus="):
            gym.set_focus(re.findall(r"[A-Za-z]+", a.split("=", 1)[1]))
    try:
        gym.loop()
    except EOFError:
        print("\nBye. Progress saved to " + PROGRESS_FILE)
    finally:
        if readline:
            try:
                readline.write_history_file(HISTORY_FILE)
            except OSError:
                pass


if __name__ == "__main__":
    main()
