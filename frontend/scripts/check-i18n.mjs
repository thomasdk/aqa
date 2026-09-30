import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const sourceRoot = path.resolve("src");
const backendApiSource = path.resolve("..", "src/service/api_app.py");
const localeSource = path.resolve("src/locales.ts");
const attributeNames = new Set(["aria-label", "aria-valuetext", "title", "placeholder", "alt"]);
const visibleSetterNames = new Set([
  "setActionError",
  "setError",
  "setInterpretationError",
  "setLocalNotice",
  "setNotice",
  "setParentSyncError",
  "setStatusText",
  "addActivity",
]);
const exactAllowlist = new Set([
  "A",
  "Q",
  "AQA",
  "Augmented Qualitative Analysis",
  "ID",
  "URL",
  "—",
  "⠋",
]);
const technicalPatterns = [
  /^https?:\/\//,
  /^127\.0\.0\.1/,
  /^\+?\s*Modell$/,
  /^[A-Z0-9_.:/^$*+?[\]{}()|\\-]+$/,
];

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(target);
    if (entry.name.endsWith(".test.ts") || entry.name.endsWith(".test.tsx")) return [];
    return entry.name.endsWith(".ts") || entry.name.endsWith(".tsx") ? [target] : [];
  });
}

function allowed(text) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized || exactAllowlist.has(normalized)) return true;
  const withoutEntities = normalized.replace(/&[a-z]+;/gi, "");
  if (!/[\p{L}\p{N}]/u.test(withoutEntities)) return true;
  return technicalPatterns.some((pattern) => pattern.test(normalized));
}

function literalText(expression) {
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return expression.text;
  }
  return null;
}

function visibleCallText(expression) {
  return (
    literalText(expression) ?? (ts.isTemplateExpression(expression) ? expression.getText() : null)
  );
}

const findings = [];
for (const file of sourceFiles(sourceRoot)) {
  const source = ts.createSourceFile(
    file,
    fs.readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );

  function report(node, text, kind) {
    if (allowed(text)) return;
    const { line, character } = source.getLineAndCharacterOfPosition(node.getStart(source));
    findings.push(
      `${path.relative(process.cwd(), file)}:${line + 1}:${character + 1} ${kind}: ${JSON.stringify(text.trim())}`,
    );
  }

  function visit(node) {
    if (ts.isJsxText(node)) {
      report(node, node.getText(source), "raw JSX text");
    } else if (ts.isJsxExpression(node) && node.expression) {
      const text = literalText(node.expression);
      if (text !== null) report(node.expression, text, "raw JSX expression");
    } else if (ts.isJsxAttribute(node) && attributeNames.has(node.name.text) && node.initializer) {
      const expression = ts.isJsxExpression(node.initializer)
        ? node.initializer.expression
        : node.initializer;
      if (expression) {
        const text = literalText(expression);
        if (text !== null) report(expression, text, `raw ${node.name.text}`);
      }
    } else if (ts.isCallExpression(node) && node.arguments.length > 0) {
      const callee = node.expression.getText(source);
      const simpleName = callee.split(".").at(-1);
      const isVisibleCall =
        visibleSetterNames.has(simpleName) ||
        callee === "window.alert" ||
        callee === "window.confirm";
      const first = node.arguments[0];
      if (isVisibleCall) {
        const text = visibleCallText(first);
        if (text !== null) report(first, text, `raw ${callee} message`);
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(source);
}

if (findings.length) {
  console.error("Raw user-interface text must use the translation catalogue:");
  console.error(findings.join("\n"));
  process.exitCode = 1;
}

const apiSource = fs.readFileSync(backendApiSource, "utf8");
const localeCatalogue = fs.readFileSync(localeSource, "utf8");
const genericErrorBlock = apiSource.match(/_GENERIC_HTTP_ERROR_CODES = \{([\s\S]*?)\n\}/);
if (!genericErrorBlock) {
  console.error("Could not locate the backend generic error-code mapping.");
  process.exitCode = 1;
} else {
  const genericCodes = [...genericErrorBlock[1].matchAll(/:\s*"([a-z_]+)"/g)].map(
    (match) => match[1],
  );
  const missingCodes = genericCodes.filter(
    (code) => !new RegExp(`\\b${code}:\\s*["']`).test(localeCatalogue),
  );
  if (missingCodes.length) {
    console.error(
      `Every generic backend error code needs an apiErrors catalogue entry: ${missingCodes.join(", ")}`,
    );
    process.exitCode = 1;
  }
}
