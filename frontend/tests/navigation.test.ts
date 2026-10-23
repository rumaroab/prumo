import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseRoute } from "../src/navigation.ts";

test("PRUMO exports keep the approved geometry, colors, names and icon sizes", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  const paths = (source: string) => Array.from(source.matchAll(/\bd="([^"]+)"/g), (match) => match[1]);
  const component = read("../src/components/PrumoBrand.tsx");
  const logo = read("../public/brand/prumo-logo.svg");
  const mono = read("../public/brand/prumo-logo-mono.svg");
  const symbol = read("../public/brand/prumo-symbol.svg");
  for (const asset of [logo, mono]) {
    assert.deepEqual(paths(asset), paths(component));
    assert.match(asset, /viewBox="0 0 1102 276"/);
  }
  assert.deepEqual(paths(symbol), paths(component).slice(0, 2));
  for (const asset of [logo, symbol]) {
    assert.match(asset, /fill:#e1e8eb/);
    assert.match(asset, /fill:#91c3d5/);
  }
  for (const asset of [logo, mono, symbol, read("../public/brand/prumo-favicon.svg")]) assert.match(asset, /role="img" aria-label="PRUMO"/);
  for (const entry of ["index.html", "public-demo.html"]) {
    const html = read(`../${entry}`);
    assert.match(html, /<title>[^<]*PRUMO<\/title>/);
    for (const icon of ["prumo-favicon.svg", "prumo-favicon.ico", "prumo-apple-touch-icon.png"]) assert.ok(html.includes(icon));
  }
  const png = readFileSync(new URL("../public/brand/prumo-apple-touch-icon.png", import.meta.url));
  assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], [180, 180]);
  const ico = readFileSync(new URL("../public/brand/prumo-favicon.ico", import.meta.url));
  assert.deepEqual(Array.from({ length: ico.readUInt16LE(4) }, (_, i) => [ico[6 + i * 16], ico[7 + i * 16]]), [[16, 16], [32, 32], [48, 48]]);
});

test("all workspace destinations and legacy archives resolve consistently", () => {
  const cases = [
    ["/", "list", undefined], ["/scenarios", "list", undefined],
    ["/scenarios/a", "overview", "overview"],
    ["/scenarios/a/experiments", "experiments", "simulations"],
    ["/scenarios/a/experiments/new", "new-experiment", "simulations"],
    ["/scenarios/a/experiments/run", "experiment", "simulations"],
    ["/scenarios/a/simulation", "simulation", "simulations"],
    ...["map", "movements", "units", "updates", "sources"].map(tab => [`/scenarios/a/mobility/${tab}`, "mobility", "mobility"]),
    ["/scenarios/a/decisions", "decisions", "decisions"],
    ...["map", "missions", "plans", "resources", "updates", "response-experiments", "rehearsals", "water-planning", "decision-support"].map(tail => [`/scenarios/a/${tail}/saved`, "archive", "archive"]),
  ];
  for (const [href, kind, workspace] of cases) {
    const route = parseRoute(href!);
    assert.equal(route.kind, kind, href); assert.equal(route.workspace, workspace, href);
  }
});
test("result IDs and data links survive URL parsing", () => {
  assert.equal(parseRoute("/scenarios/a/simulation?run=run%20one").runId, "run one");
  assert.equal(parseRoute("/scenarios/a/decisions?view=data&run=b").tab, "data");
  assert.equal(parseRoute("/scenarios/a/experiments/result/").runId, "result");
  assert.equal(parseRoute("/scenarios/a/mobility").tab, "map");
});
test("public briefs stay standalone and unknown routes do not become occurrence lists", () => {
  assert.equal(parseRoute("/brief/token").token, "token");
  for (const href of ["/unknown", "/scenarios/a/wrong", "/scenarios/a/mobility/wrong"]) assert.equal(parseRoute(href).kind, "missing");
});

test("decision perspectives have stable direct links and keep legacy data links", () => {
  for (const [query, perspective, title] of [["", "water", "Abastecimento"], ["?perspective=access", "access", "Acessos"], ["?perspective=population", "population", "Apoio à população"], ["?perspective=unknown", "water", "Abastecimento"]]) {
    const route = parseRoute(`/scenarios/a/decisions${query}`);
    assert.equal(route.perspective, perspective);
    assert.equal(route.title, title);
  }
  assert.equal(parseRoute("/scenarios/a/decisions?view=data&perspective=access").perspective, undefined);
});
