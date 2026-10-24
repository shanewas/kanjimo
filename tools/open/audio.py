"""Audio stage: Kanji alive native recordings matched by written form and reading.

The recordings are not downloaded here. Each matched word gets an audio entry
pointing at audio/kanjialive/<file>.mp3 and the media manifest records which
archive member a later fetch step copies there (file naming per the
examples-audio README: <kname>_06_<a..l>.<ext>, letter = index in `examples`).
"""
ARCHIVE = "https://media.kanjialive.com/examples_audio/audio-mp3.zip"
LICENCE = "CC-BY-4.0"
LETTERS = "abcdefghijkl"


def match_audio(words, ka):
    """words: [{form, readings}] ; ka: read_kanjialive rows. -> ({form: [entry]}, manifest)."""
    by_pair = {}
    for kanji, kname, idx, form, readings, _ in ka:
        for r in readings:
            by_pair.setdefault((form, r), (kanji, kname, idx, r))
    audio, manifest = {}, []
    for w in words:
        hit = next((by_pair[(w["form"], r)] for r in w["readings"] if (w["form"], r) in by_pair), None)
        if not hit:
            continue
        kanji, kname, idx, reading = hit
        name = "%s_06_%s.mp3" % (kname, LETTERS[idx])
        url = "audio/kanjialive/" + name
        audio[w["form"]] = [{"url": url, "content_type": "audio/mpeg", "source": "kanjialive", "licence": LICENCE}]
        manifest.append({"url": url, "archive": ARCHIVE, "member": "audio-mp3/" + name,
                         "word": w["form"], "reading": reading, "kanji": kanji,
                         "source": "kanjialive", "licence": LICENCE})
    return audio, manifest
