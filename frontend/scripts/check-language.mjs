import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "..");
const catalog = JSON.parse(fs.readFileSync(path.join(root, "src/ptPT.json"), "utf8"));
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const errors = [];
if (!/<html lang="pt-PT">/.test(html)) errors.push("index.html must declare pt-PT");

const files = ["App.tsx", "loading.tsx", ...fs.readdirSync(path.join(root, "src/components"))
  .filter(name => name.endsWith(".tsx") && !["OperationsPage.tsx", "ExerciseWorkspace.tsx"].includes(name))
  .map(name => `components/${name}`)];
const english = /\b(?:the|and|before|after|available|unavailable|scenario|result|review|reported|current|source|road|roads|run|open|create|save|delete|next|previous|loading|simulation|fire|water|observed|planned|unknown|route|workspace|please|select|click|manage|forecast|layer|engine)\b/i;

for (const relative of files) {
  const filename = path.join(root, "src", relative);
  const source = fs.readFileSync(filename, "utf8");
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (/new Intl\.DateTimeFormat\(undefined|\.toLocale(?:Date|Time)?String\(\)/.test(source))
    errors.push(`${relative}: use the PT-PT formatters for displayed dates and numbers`);
  if (/fireline-language|setLanguage|navigator\.language/.test(source))
    errors.push(`${relative}: partial language switching is disabled until translation parity exists`);
  function visit(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)
        && ["t", "uiText"].includes(node.expression.text) && ts.isStringLiteral(node.arguments[0])
        && !Object.hasOwn(catalog, node.arguments[0].text))
      errors.push(`${relative}:${tree.getLineAndCharacterOfPosition(node.pos).line + 1}: missing PT-PT catalog entry for ${JSON.stringify(node.arguments[0].text)}`);
    if (ts.isJsxText(node)) {
      const value = node.text.trim();
      if (english.test(value)) errors.push(`${relative}:${tree.getLineAndCharacterOfPosition(node.pos).line + 1}: untranslated visible text ${JSON.stringify(value)}`);
    }
    if (ts.isJsxAttribute(node) && ["placeholder", "title", "aria-label", "alt"].includes(node.name.text)
        && node.initializer && ts.isStringLiteral(node.initializer) && english.test(node.initializer.text))
      errors.push(`${relative}:${tree.getLineAndCharacterOfPosition(node.pos).line + 1}: untranslated ${node.name.text} ${JSON.stringify(node.initializer.text)}`);
    if (ts.isJsxAttribute(node) && ["placeholder", "title", "aria-label", "alt"].includes(node.name.text)
        && node.initializer && ts.isJsxExpression(node.initializer)) {
      function checkAttributeText(child) {
        if (ts.isCallExpression(child) && ts.isIdentifier(child.expression) && ["t", "uiText", "tr"].includes(child.expression.text)) return;
        if (ts.isStringLiteral(child) && english.test(child.text))
          errors.push(`${relative}:${tree.getLineAndCharacterOfPosition(child.pos).line + 1}: untranslated ${node.name.text} ${JSON.stringify(child.text)}`);
        ts.forEachChild(child, checkAttributeText);
      }
      checkAttributeText(node.initializer);
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exitCode = 1;
} else console.log("PT-PT interface checks passed");
