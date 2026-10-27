// Cross-check scenarios: run the upstream Meterless H-MEM TypeScript reference
// on fixed inputs and print JSON. The output is frozen in
// tests/golden/hmem_reference_output.json and tests/test_hmem_golden.py replays
// the same scenarios through the Python port and compares.
//
// Regenerate (needs Node 22 + a clone of github.com/Meterless/Meterless):
//   HMEM_REFERENCE_SRC=/abs/path/to/Meterless/engines/hmem/reference/src/index.ts \
//     npx -y tsx@4 scripts/xcheck/reference_scenarios.ts > tests/golden/hmem_reference_output.json
//
// Scenarios are mirrored line for line in tests/test_hmem_golden.py.

const refPath = process.env.HMEM_REFERENCE_SRC ?? "../Meterless/engines/hmem/reference/src/index.ts";
const ref = await import(refPath);
const { HMEM, embed, cosine, tokenize } = ref;

const T0 = 1750000000000;
const texts = [
  "we deploy the api with docker on mondays",
  "Biffa Waste Services Ltd supplies Woking and Guildford",
  "always enable telemetry uploads for diagnostics",
  "never enable telemetry uploads for diagnostics",
  "Council Tax Support band cap is Band D in Woking from April 2025",
];
const out: any = { tokens: {}, embed: {}, cosine: {}, query: {}, conflict: {} };
for (const t of texts) { out.tokens[t] = tokenize(t); out.embed[t] = embed(t); }
out.cosine["a2b3"] = cosine(embed(texts[2]), embed(texts[3]));

const h = new HMEM({ clock: () => T0 });
const m1 = h.add({ content: texts[0], confidence: 0.9, layer: "long_term", source: "x" });
const m2 = h.add({ content: "we deploy the api with docker on fridays", confidence: 0.9, layer: "long_term", source: "x" });
const m3 = h.add({ content: texts[1], confidence: 0.8, layer: "working", type: "factual", source: "x" });
m2.supersededBy = m1.id;
const q = h.query("when do we deploy the api with docker", { threshold: 0, topN: 10 });
out.query = { ids: q.memories.map((m: any) => m.memory.id), scores: q.trace.scores, context: q.context, strategy: q.trace.strategy };
out.entities = { m3: m3.entities, domain: m3.domain, namespace: m3.namespace };

const h2 = new HMEM({ clock: () => T0 });
const a = h2.add({ content: texts[2], confidence: 0.95, source: "x" });
const b = h2.add({ content: texts[3], confidence: 0.2, source: "x" });
const found = h2.conflicts.scan();
out.conflict = {
  n: found.length,
  confidence: found[0]?.confidence,
  outcome: h2.conflicts.autoResolve(found[0]),
  loserSupersededBy: [h2.store.get(a.id)!.supersededBy, h2.store.get(b.id)!.supersededBy],
};
console.log(JSON.stringify(out));
