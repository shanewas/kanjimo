// Text helper tests: keyword marks. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { marks } from "../app/text.js";

describe("marks", () => {
  const join = (segs) => segs.map((s) => (s.mark ? `[${s.mark}:${s.text}]` : s.text)).join("");

  it("marks whole English words in any case, plurals included", () => {
    const t = "You find a toe on the ground. Toes above grounds, not tomatoes.";
    const terms = [{ text: "Toe", mark: "radical" }, { text: "Ground", mark: "radical" }];
    assert.equal(join(marks(t, terms)),
      "You find a [radical:toe] on the [radical:ground]. [radical:Toes] above [radical:grounds], not tomatoes.");
  });

  it("marks kana only as a whole run", () => {
    const t = "Joe (じょう) is not じょうず.";
    assert.equal(join(marks(t, [{ text: "じょう", mark: "reading" }])), "Joe ([reading:じょう]) is not じょうず.");
  });

  it("prefers the longer term and leaves text alone without terms", () => {
    const t = "Lift something up.";
    const terms = [{ text: "Lift", mark: "kanji" }, { text: "Lift Something", mark: "vocabulary" }];
    assert.equal(join(marks(t, terms)), "[vocabulary:Lift something] up.");
    assert.deepEqual(marks(t, []), [{ text: t, mark: null }]);
    assert.deepEqual(marks(t, [{ text: " ", mark: "x" }]), [{ text: t, mark: null }]);
  });
});
