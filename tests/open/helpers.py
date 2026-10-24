"""Shared fixture helpers for the open-data pipeline tests (stdlib only, temp dirs only)."""
import bz2
import gzip
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(REPO, "tools", "open")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


def gz(path, text):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(text)
    return path


def bz(path, text):
    with bz2.open(path, "wt", encoding="utf-8") as f:
        f.write(text)
    return path


def zipped(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return path


def text(path, body):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path


KANJIDIC2 = """<?xml version="1.0" encoding="UTF-8"?>
<kanjidic2>
<header><file_version>4</file_version><database_version>2026-281</database_version>
<date_of_creation>2026-10-08</date_of_creation></header>
<character><literal>上</literal><misc><grade>1</grade><stroke_count>3</stroke_count><freq>35</freq><jlpt>4</jlpt></misc>
<reading_meaning><rmgroup>
<reading r_type="pinyin">shang4</reading>
<reading r_type="ja_on">ジョウ</reading><reading r_type="ja_on">ショウ</reading>
<reading r_type="ja_kun">うえ</reading><reading r_type="ja_kun">-うえ</reading><reading r_type="ja_kun">あ.げる</reading>
<meaning>above</meaning><meaning>up</meaning><meaning m_lang="fr">dessus</meaning>
</rmgroup><nanori>あげ</nanori></reading_meaning></character>
<character><literal>一</literal><misc><grade>1</grade><stroke_count>1</stroke_count><freq>2</freq></misc>
<reading_meaning><rmgroup><reading r_type="ja_on">イチ</reading><reading r_type="ja_kun">ひと-</reading>
<meaning>one</meaning><meaning>one radical (no. 1)</meaning></rmgroup></reading_meaning></character>
<character><literal>手</literal><misc><grade>1</grade><stroke_count>4</stroke_count><freq>60</freq></misc>
<reading_meaning><rmgroup><reading r_type="ja_on">シュ</reading><reading r_type="ja_kun">て</reading>
<meaning>hand</meaning></rmgroup></reading_meaning></character>
<character><literal>卜</literal><misc><grade>9</grade><stroke_count>2</stroke_count></misc>
<reading_meaning><rmgroup><reading r_type="ja_on">ボク</reading><meaning>divining</meaning><meaning>fortune-telling</meaning></rmgroup></reading_meaning></character>
<character><literal>箇</literal><misc><grade>8</grade><stroke_count>14</stroke_count></misc>
<reading_meaning><rmgroup><reading r_type="ja_on">カ</reading><meaning>counter for articles</meaning></rmgroup></reading_meaning></character>
</kanjidic2>
"""

SVG_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 109 109">\n'


def svg(code, body):
    return (SVG_HEAD + '<g id="kvg:StrokePaths_%s" style="fill:none;">\n%s\n</g>\n'
            '<g id="kvg:StrokeNumbers_%s"><text>1</text></g></svg>' % (code, body, code))


KANJIVG = {
    # 上 = 卜 (top) + 一 (bottom)
    "kanji/04e0a.svg": svg("04e0a", '<g id="kvg:04e0a" kvg:element="上">'
                           '<g id="kvg:04e0a-g1" kvg:element="卜" kvg:position="top"><path id="s1" kvg:type="a" d="M1,1"/><path id="s2" d="M2,2"/></g>'
                           '<g id="kvg:04e0a-g2" kvg:element="一" kvg:radical="tradit" kvg:position="bottom"><path id="s3" d="M3,3"/></g></g>'),
    # 一 is atomic
    "kanji/04e00.svg": svg("04e00", '<g id="kvg:04e00" kvg:element="一"><path id="s1" d="M0,0"/></g>'),
    # a kanji with an unnamed wrapper, a split part (kvg:part) and a CDP element
    "kanji/056fd.svg": svg("056fd", '<g id="kvg:056fd" kvg:element="国">'
                           '<g id="w"><g id="g1" kvg:element="囗" kvg:part="1"><path d="M1,1"/></g>'
                           '<g id="g2" kvg:element="CDP-8BC4"><path d="M5,5"/></g>'
                           '<g id="g3" kvg:element="囗" kvg:part="2"><path d="M9,9"/></g></g></g>'),
    # 林 = 木 + 木: the same element twice, no kvg:part, so two parts
    "kanji/06797.svg": svg("06797", '<g id="kvg:06797" kvg:element="林">'
                           '<g id="g1" kvg:element="木" kvg:position="left"><path d="M1,1"/></g>'
                           '<g id="g2" kvg:element="木" kvg:position="right"><path d="M2,2"/></g></g>'),
}

JMDICT = """<?xml version="1.0" encoding="UTF-8"?>
<!-- JMdict created: 2026-10-08 -->
<!DOCTYPE JMdict [
<!ENTITY n "noun (common) (futsuumeishi)">
<!ENTITY uk "word usually written using kana alone">
<!ENTITY v5r "Godan verb with 'ru' ending">
<!ENTITY vt "transitive verb">
<!ENTITY arch "archaic">
<!ENTITY n-pr "proper noun">
<!ENTITY prt "particle">
<!ENTITY rK "rarely used kanji form">
]>
<JMdict>
<entry><ent_seq>1</ent_seq><k_ele><keb>上</keb><ke_pri>news1</ke_pri><ke_pri>nf01</ke_pri></k_ele>
<r_ele><reb>うえ</reb><re_pri>news1</re_pri></r_ele><r_ele><reb>かみ</reb></r_ele>
<sense><pos>&n;</pos><gloss>above</gloss><gloss>up (high)</gloss></sense>
<sense><stagr>かみ</stagr><pos>&n;</pos><gloss>upper part</gloss></sense></entry>
<entry><ent_seq>2</ent_seq><k_ele><keb>有難う</keb></k_ele><k_ele><keb>有り難う</keb><ke_inf>&rK;</ke_inf></k_ele>
<r_ele><reb>ありがとう</reb><re_pri>ichi1</re_pri></r_ele>
<sense><pos>&n;</pos><misc>&uk;</misc><gloss>thank you</gloss></sense></entry>
<entry><ent_seq>3</ent_seq><k_ele><keb>上がる</keb><ke_pri>ichi1</ke_pri></k_ele><r_ele><reb>あがる</reb></r_ele>
<sense><pos>&v5r;</pos><pos>&vt;</pos><gloss>to rise</gloss></sense></entry>
<entry><ent_seq>4</ent_seq><k_ele><keb>上古</keb><ke_pri>news1</ke_pri></k_ele><r_ele><reb>じょうこ</reb></r_ele>
<sense><pos>&n;</pos><misc>&arch;</misc><gloss>ancient times</gloss></sense></entry>
<entry><ent_seq>5</ent_seq><k_ele><keb>上野</keb><ke_pri>news1</ke_pri></k_ele><r_ele><reb>うえの</reb></r_ele>
<sense><pos>&n-pr;</pos><gloss>Ueno</gloss></sense></entry>
<entry><ent_seq>6</ent_seq><r_ele><reb>は</reb><re_pri>spec1</re_pri></r_ele>
<sense><pos>&prt;</pos><gloss>topic marker</gloss></sense></entry>
<entry><ent_seq>7</ent_seq><k_ele><keb>一つ</keb></k_ele><r_ele><reb>ひとつ</reb></r_ele>
<sense><pos>&n;</pos><gloss>one</gloss></sense></entry>
<entry><ent_seq>8</ent_seq><k_ele><keb>上手</keb><ke_pri>news1</ke_pri></k_ele><r_ele><reb>じょうず</reb></r_ele>
<sense><pos>&n;</pos><gloss>skill</gloss></sense></entry>
</JMdict>
"""

TANOS_VOCAB = """<html><body><table>
<tr><th>Kanji</th><th>Hiragana</th><th>English</th></tr>
<tr><td>一つ</td><td>ひとつ</td><td>one</td></tr>
<tr><td></td><td>ありがとう</td><td>thank you</td></tr>
<tr><td>上/上方</td><td>うえ</td><td>above</td></tr>
</table></body></html>
"""
TANOS_KANJI = """<html><body><table>
<tr><th>Kanji</th><th>Onyomi</th><th>Kunyomi</th><th>English</th></tr>
<tr><td>上 </td><td>ジョウ</td><td>うえ</td><td>above</td></tr>
<tr><td>一 </td><td>イチ</td><td>ひと</td><td>one</td></tr>
</table></body></html>
"""

KA_DATA = ('kanji,kname,kstroke,kmeaning,kgrade,kunyomi_ja,kunyomi,onyomi_ja,onyomi,examples,radical\n'
           '上,jou-ue,3,above,1,うえ,ue,ジョウ,jou,"[ [ ""上（うえ）"", ""above"" ], [ ""上手（じょうず/うわて）"", ""skill"" ] ]",一\n')
