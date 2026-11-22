"""OSINT Panel command line — use the panel's tools without opening the web interface.

Examples:
  ./osint search torvalds                       # detect type, run the default tools, print merged results
  ./osint search someone@example.com --json     # machine-readable output
  ./osint search example.com --tools whois,crtsh,favicon --csv --out result.csv
  ./osint search "Ada Lovelace" --all --save-case "Ada"   # every tool for the type, save findings to a case
  ./osint run github username=torvalds           # one tool with explicit inputs
  ./osint tools --type email                     # which tools accept e-mails
  ./osint detect 0x742d35Cc6634C0532925a3b844Bc454e4438f44e
  ./osint watch 3            # re-scan case 3 now and print changes
  ./osint archive 3          # archive every link of case 3 as evidence
  ./osint serve              # start the web panel
"""
import argparse
import csv
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OSINT_QUIET", "1")


def _boot(lang="en"):
    import app  # noqa: F401  — registers tools2 + plugins
    import catalog
    import runner
    import store
    import tools
    global TITLE
    TITLE = {t["id"]: t["title"] for t in tools.public_registry(lang)}
    return app, catalog, runner, store, tools


TITLE = {}


def _print_table(items, info, show_info):
    if not items and not (show_info and info):
        print("No results.")
        return
    w = max([len(x["title"][:30]) for x in items] + [5])
    for x in items:
        tools = ", ".join(x["tools"])
        flag = "?" if x["status"] == "maybe" else "✓"
        print(f"{flag} {x['title'][:30]:<{w}}  {x['url']}")
        print(f"  {'':<{w}}  found by {len(x['tools'])}: {tools}")
    if show_info and info:
        print("\n-- info --")
        for r in info:
            print(f"[{r['tool']}] {r['title']}{' — ' + str(r['detail'])[:120] if r['detail'] else ''}{'  ' + r['url'] if r['url'] else ''}")


def cmd_search(a):
    app, catalog, runner, store, tools = _boot(a.lang)
    import merge
    only = [t.strip() for t in a.tools.split(",")] if a.tools else None
    typ, plan = runner.plan(a.value, a.type, only, a.all)
    if not plan:
        sys.exit(f"No tools to run for type '{typ}'. See: osint tools --type {typ}")
    err = sys.stderr
    print(f"type: {typ} · tools: {', '.join(t for t, _ in plan)}", file=err)
    t0 = time.time()

    def progress(tid, rows, e):
        n = sum(1 for r in rows if r.get("status") in ("found", "maybe"))
        print(f"  {'!' if e else '✓'} {TITLE.get(tid, tid)}: {n} found{' — ' + e[:80] if e else ''}", file=err)

    res = runner.run_many(plan, lang=a.lang, workers=a.workers, budget_s=a.budget,
                          log=(lambda m: print("    " + m, file=err)) if a.verbose else None, on_result=progress)
    titled = {TITLE.get(t, t): r["rows"] for t, r in res.items()}
    items, info = merge.merge(titled, typ)
    print(f"{len(items)} distinct findings · {sum(len(x['tools']) > 1 for x in items)} by several tools · {time.time() - t0:.0f}s", file=err)
    out = open(a.out, "w", newline="") if a.out else sys.stdout
    if a.json:
        json.dump({"value": a.value, "type": typ, "results": items, "info": info,
                   "tools": {TITLE.get(t, t): {"error": r["error"], "seconds": r["seconds"]} for t, r in res.items()}},
                  out, ensure_ascii=False, indent=2)
        out.write("\n")
    elif a.csv:
        w = csv.writer(out)
        w.writerow(["title", "url", "status", "tools", "detail"])
        for x in items:
            w.writerow([x["title"], x["url"], x["status"], "; ".join(x["tools"]), x["detail"]])
    else:
        if a.out:
            buf = io.StringIO()
            sys.stdout, old = buf, sys.stdout
            _print_table(items, info, a.info)
            sys.stdout = old
            out.write(buf.getvalue())
        else:
            _print_table(items, info, a.info)
    if a.save_case:
        cid = next((c["id"] for c in store.list_cases() if c["name"] == a.save_case), None) or store.create_case(a.save_case)
        added = store.add_items(cid, "unified", a.value, [
            {"title": x["title"], "url": x["url"], "detail": x["detail"], "image": x["image"], "status": x["status"],
             "tags": ", ".join(x["tools"]), "meta": {**x["meta"], "Bulan araçlar": ", ".join(x["tools"])}} for x in items])
        print(f"saved {added} findings to case #{cid} “{a.save_case}”", file=err)


def cmd_run(a):
    app, catalog, runner, store, tools = _boot(a.lang)
    if a.tool not in tools.BY_ID:
        sys.exit(f"Unknown tool: {a.tool}")
    inp = dict(kv.split("=", 1) for kv in a.inputs)
    rows, err = runner.run_tool(a.tool, inp, a.lang, log=(lambda m: print("  " + m, file=sys.stderr)) if a.verbose else None)
    if a.json:
        print(json.dumps({"rows": rows, "error": err}, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"[{r['status']}] {r['title']}{' — ' + str(r['detail'])[:140] if r['detail'] else ''}{'  ' + r['url'] if r['url'] else ''}")
        if err:
            print("error:", err, file=sys.stderr)
    sys.exit(1 if err else 0)


def cmd_tools(a):
    app, catalog, runner, store, tools = _boot(a.lang)
    m = catalog.build(tools.REGISTRY)
    if a.type:
        for x in m.get(a.type, []):
            print(f"{x['id']:<18} {'default' if x['default'] is True else ('optional' if x['default'] is False else x['default']):<20} {TITLE.get(x['id'], 'Sherlock')}")
        return
    from about_en import GROUPS_EN
    for t in tools.REGISTRY:
        fields = ", ".join(f["name"] + ("*" if f.get("required") else "") for f in t["fields"])
        group = GROUPS_EN.get(t["group"], t["group"]) if a.lang == "en" else t["group"]
        print(f"{t['id']:<18} {group:<14} {TITLE.get(t['id'], t['title'])[:34]:<36} {fields}")


def cmd_detect(a):
    import catalog
    print(catalog.detect_type(a.value))


def cmd_watch(a):
    app, catalog, runner, store, tools = _boot(a.lang)
    import watch
    print(json.dumps(watch.run_case(a.case_id, a.lang, log=lambda m: print(m, file=sys.stderr)), ensure_ascii=False))
    for c in store.list_changes(a.case_id, 50):
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(c['ts']))}  {c['kind']}: {c['title']}  {c['url']}")


def cmd_archive(a):
    app, catalog, runner, store, tools = _boot(a.lang)
    import evidence
    c = store.get_case(a.case_id) or sys.exit("case not found")
    for it in c["items"]:
        if not (it.get("url") or "").startswith("http"):
            continue
        try:
            r = evidence.capture(a.case_id, it)
            print(f"{'✓' if not r['error'] else '!'} {it['url']}  png:{r['png_sha256'][:12]} html:{r['html_sha256'][:12]} {r['error']}")
        except Exception as e:
            print(f"! {it['url']}  {e}")


def cmd_serve(a):
    import app
    app.main()


def main(argv=None):
    p = argparse.ArgumentParser(prog="osint", description="OSINT Panel from the command line.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("Examples:")[1])
    p.add_argument("--lang", default="en", choices=["en", "tr"], help="language of tool messages (default en)")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("search", help="smart search: detect the type and run every matching tool")
    s.add_argument("value")
    s.add_argument("--type", choices=["username", "email", "phone", "name", "domain", "ip", "url", "crypto"])
    s.add_argument("--tools", help="comma-separated tool ids (overrides defaults)")
    s.add_argument("--all", action="store_true", help="also run optional / slow tools")
    s.add_argument("--json", action="store_true")
    s.add_argument("--csv", action="store_true")
    s.add_argument("--out", help="write output to a file")
    s.add_argument("--info", action="store_true", help="also print non-profile info rows")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--budget", type=int, default=900, help="time budget in seconds")
    s.add_argument("--save-case", metavar="NAME", help="save the merged findings to a case")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_search)
    r = sp.add_parser("run", help="run one tool: osint run <tool> field=value …")
    r.add_argument("tool")
    r.add_argument("inputs", nargs="*")
    r.add_argument("--json", action="store_true")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)
    t = sp.add_parser("tools", help="list tools")
    t.add_argument("--type")
    t.set_defaults(fn=cmd_tools)
    d = sp.add_parser("detect", help="print the detected input type")
    d.add_argument("value")
    d.set_defaults(fn=cmd_detect)
    w = sp.add_parser("watch", help="re-scan a case now and print changes")
    w.add_argument("case_id", type=int)
    w.set_defaults(fn=cmd_watch)
    ar = sp.add_parser("archive", help="archive every link of a case as evidence")
    ar.add_argument("case_id", type=int)
    ar.set_defaults(fn=cmd_archive)
    sv = sp.add_parser("serve", help="start the web panel")
    sv.set_defaults(fn=cmd_serve)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
