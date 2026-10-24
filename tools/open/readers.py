"""Readers for the pinned source files. Each returns plain dicts/lists.

The files are data: nothing in them is imported or executed. Parsing follows
the formats described in each file's own header or DTD.
"""
import bz2
import csv
import gzip
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from html.parser import HTMLParser

from common import hira

NULL = "\\" + "N"      # Tatoeba's empty-field marker


# ---- KANJIDIC2 ----------------------------------------------------------------

def read_kanjidic2(path):
    """-> ({literal: {...}}, header dict)."""
    chars, header = {}, {}
    with gzip.open(path, "rb") as f:
        for _, el in ET.iterparse(f):
            if el.tag == "header":
                header = {"database_version": el.findtext("database_version"),
                          "date_of_creation": el.findtext("date_of_creation")}
            if el.tag != "character":
                continue
            on, kun, meanings = [], [], []
            rm = el.find("reading_meaning")
            nanori = []
            if rm is not None:
                for rg in rm.findall("rmgroup"):
                    for r in rg.findall("reading"):
                        if r.get("r_type") == "ja_on":
                            on.append(r.text)
                        elif r.get("r_type") == "ja_kun":
                            kun.append(r.text)
                    meanings += [m.text for m in rg.findall("meaning") if m.get("m_lang") is None]
                nanori = [n.text for n in rm.findall("nanori")]
            misc = el.find("misc")

            def num(tag):
                v = misc.findtext(tag) if misc is not None else None
                return int(v) if v else None
            chars[el.findtext("literal")] = {
                "on": on, "kun": kun, "nanori": nanori, "meanings": meanings,
                "grade": num("grade"), "freq": num("freq"), "jlpt": num("jlpt"),
                "strokes": num("stroke_count") or 0,
                "rad_names": [x.text for x in misc.findall("rad_name")] if misc is not None else []}
            el.clear()
    return chars, header


# ---- KanjiVG ------------------------------------------------------------------

TAG = re.compile(r"<(g|path)\b([^>]*?)(/?)>|</(g)>")
ATTR = re.compile(r'([\w:]+)="([^"]*)"')


def kvg_tree(text):
    root = {"tag": "root", "attrs": {}, "kids": []}
    stack = [root]
    for m in TAG.finditer(text):
        if m.group(4):
            stack.pop()
            continue
        attrs = {k.replace("kvg:", ""): v for k, v in ATTR.findall(m.group(2))}
        node = {"tag": m.group(1), "attrs": attrs, "kids": []}
        stack[-1]["kids"].append(node)
        if m.group(1) == "g" and not m.group(3):
            stack.append(node)
    return root


def kvg_paths(node):
    out = []
    if node["tag"] == "path" and "d" in node["attrs"]:
        out.append(node["attrs"]["d"])
    for k in node["kids"]:
        out += kvg_paths(k)
    return out


def kvg_parts(node):
    """Named child components, wrappers flattened, split parts merged, in stroke order."""
    found = []
    for k in node["kids"]:
        if k["tag"] != "g":
            continue
        if "element" in k["attrs"]:
            found.append(k)
        else:
            found += kvg_parts_nodes(k)
    parts, split = [], {}
    for k in found:
        e = k["attrs"]["element"]
        # only kvg:part pieces are one component cut in two; a repeated element
        # without it is a second copy (林 is 木 + 木) and stays its own part
        if "part" in k["attrs"] and e in split:
            split[e]["nodes"].append(k)
            continue
        p = {"element": e, "position": k["attrs"].get("position", ""),
             "radical": bool(k["attrs"].get("radical")), "nodes": [k]}
        if "part" in k["attrs"]:
            split[e] = p
        parts.append(p)
    return parts


def kvg_parts_nodes(node):
    out = []
    for k in node["kids"]:
        if k["tag"] != "g":
            continue
        if "element" in k["attrs"]:
            out.append(k)
        else:
            out += kvg_parts_nodes(k)
    return out


def kvg_file_name(glyph):
    return "kanji/%05x.svg" % ord(glyph)


def read_kanjivg(path, glyphs):
    """-> {glyph: {"parts": [...], "strokes": n, "top": node}} for glyphs with a file."""
    out = {}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for g in sorted(glyphs):
            fn = kvg_file_name(g)
            if fn not in names:
                continue
            tree = kvg_tree(z.read(fn).decode("utf-8"))
            top = tree["kids"][0]["kids"][0]          # StrokePaths wrapper -> kanji group
            parts = kvg_parts(top)
            if len(parts) == 1 and parts[0]["element"] == g:   # variant wrapper of itself
                parts = kvg_parts(parts[0]["nodes"][0])
            parts = [p for p in parts if p["element"] != g]
            out[g] = {"parts": parts, "strokes": len(kvg_paths(top)), "top": top}
    return out


def svg_for(nodes, credit):
    paths = [d for n in nodes for d in kvg_paths(n)]
    body = "".join('<path d="%s"/>' % d for d in paths)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 109 109">'
            '<!-- %s -->'
            '<g fill="none" stroke="currentColor" stroke-width="3" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g></svg>\n' % (credit, body))


# ---- JMdict -------------------------------------------------------------------

PRI_COMMON = {"news1", "ichi1", "spec1", "spec2", "gai1"}


def jmdict_entities(path):
    """DTD entity table, replacement text -> short code (ET expands entities)."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        head = f.read(600000)
    codes = {}
    for code, text in re.findall(r'<!ENTITY (\S+) "([^"]*)">', head):
        codes.setdefault(text, code)
    m = re.search(r"JMdict created: (\d{4}-\d{2}-\d{2})", head)
    return codes, (m.group(1) if m else "")


def nf_rank(tags):
    nf = [int(t[2:]) for t in tags if t.startswith("nf")]
    return min(nf) if nf else None


def read_jmdict(path, keep):
    """Compact entries for which keep(entry) is true.

    entry = {"seq", "k": [{"text", "pri", "inf"}], "r": [{"text", "pri", "inf",
    "restr", "nokanji"}], "s": [{"pos", "misc", "gloss", "stagk", "stagr"}]}
    with pos/misc/inf as JMdict short codes.
    """
    codes, _ = jmdict_entities(path)
    entries = []
    n = 0
    with gzip.open(path, "rb") as f:
        for _, el in ET.iterparse(f):
            if el.tag != "entry":
                continue
            n += 1
            ent = {"seq": int(el.findtext("ent_seq")), "k": [], "r": [], "s": []}
            for k in el.findall("k_ele"):
                ent["k"].append({"text": k.findtext("keb"),
                                 "pri": [p.text for p in k.findall("ke_pri")],
                                 "inf": [codes.get(i.text, i.text) for i in k.findall("ke_inf")]})
            for r in el.findall("r_ele"):
                ent["r"].append({"text": r.findtext("reb"),
                                 "pri": [p.text for p in r.findall("re_pri")],
                                 "inf": [codes.get(i.text, i.text) for i in r.findall("re_inf")],
                                 "restr": [x.text for x in r.findall("re_restr")],
                                 "nokanji": r.find("re_nokanji") is not None})
            for s in el.findall("sense"):
                ent["s"].append({"pos": [codes.get(p.text, p.text) for p in s.findall("pos")],
                                 "misc": [codes.get(m.text, m.text) for m in s.findall("misc")],
                                 "gloss": [g.text for g in s.findall("gloss") if g.text and g.get("{http://www.w3.org/XML/1998/namespace}lang") in (None, "eng")],
                                 "stagk": [x.text for x in s.findall("stagk")],
                                 "stagr": [x.text for x in s.findall("stagr")]})
            if keep(ent):
                entries.append(ent)
            el.clear()
    return entries, n


# ---- tanos JLPT lists (HTML tables) --------------------------------------------

class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def html_rows(path):
    p = _Tables()
    with open(path, encoding="utf-8", errors="replace") as f:
        p.feed(f.read())
    return p.rows


def read_tanos(paths):
    """paths: {(level, 'vocab'|'kanji'): file}. -> {level: {"vocab": [(form, kana, en)], "kanji": set}}"""
    out = {}
    for (lv, kind), path in sorted(paths.items()):
        rows = html_rows(path)
        d = out.setdefault(lv, {"vocab": [], "kanji": set()})
        if kind == "kanji":
            d["kanji"] = {r[0].strip() for r in rows[1:] if r and len(r[0].strip()) == 1}
        else:
            for r in rows[1:]:
                if len(r) >= 3 and (r[0].strip() or r[1].strip()):
                    d["vocab"].append((r[0].strip(), r[1].strip(), r[2].strip()))
    return out


# ---- Tatoeba ------------------------------------------------------------------

def read_links(path):
    """jp id -> sorted list of linked en ids (every pair in the jpn-eng export)."""
    links = defaultdict(set)
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            a, b = line.rstrip("\n").split("\t")
            links[a].add(b)
    return {k: sorted(v, key=int) for k, v in links.items()}


def read_jpn(path, wanted_ids):
    """id -> (text, username or '') for ids in wanted_ids."""
    out = {}
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[0] in wanted_ids:
                out[p[0]] = (p[2], "" if p[3] == NULL else p[3])
    return out


def read_eng(path, wanted_ids):
    """id -> (text, username or '') from the detailed export: CC BY 2.0 FR needs
    the author of each English translation too, which the plain export omits."""
    return read_jpn(path, wanted_ids)


# ---- Tanaka / Tatoeba examples.utf (B-line word index) -------------------------

TOK = re.compile(r"^([^\(\[\{~]+)(?:\(([^\)]*)\))?(?:\[(\d+)\])?(?:\{([^\}]*)\})?(~)?$")


def read_examples(path, forms):
    """-> ({jp_id: {"jp", "en", "en_id", "hits": [(headword, reading, surface, checked)]}}, lemma Counter).

    `#ID=<eng id>_<jpn id>` on each A line names the Tatoeba sentence ids.
    The file names no author for either side.
    Only B-line tokens whose headword is in `forms` are kept.
    """
    out, lemma = {}, Counter()
    cur = None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("A: "):
                body, _, tail = line[3:].rstrip("\n").rpartition("#ID=")
                jp, _, en = body.partition("\t")
                ids = tail.split("_")
                cur = ids[1] if len(ids) == 2 else None
                if cur:
                    out[cur] = {"jp": jp, "en": en, "en_id": ids[0], "hits": []}
            elif line.startswith("B: ") and cur:
                for tok in line[3:].split():
                    m = TOK.match(tok)
                    if not m:
                        continue
                    head = m.group(1)
                    lemma[head] += 1
                    if head in forms:
                        out[cur]["hits"].append((head, m.group(2), m.group(4), bool(m.group(5))))
    return out, lemma


# ---- Kanji alive example words -------------------------------------------------

def read_kanjialive(path):
    """-> [(kanji, kname, index, form, [readings], gloss)] in file order."""
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                examples = json.loads(row["examples"])
            except json.JSONDecodeError:
                continue
            for i, pair in enumerate(examples):
                if len(pair) != 2:
                    continue
                m = re.match(r"^(.*?)（(.*?)）$", pair[0])
                if not m:
                    continue
                readings = [hira(r.strip()) for r in m.group(2).split("/") if r.strip()]
                out.append((row["kanji"], row["kname"], i, m.group(1).strip(), readings, pair[1]))
    return out
