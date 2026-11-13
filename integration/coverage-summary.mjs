import { readFileSync } from "node:fs";
import { join } from "node:path";

const blockPattern = /^(.+):(\d+)\.(\d+),(\d+)\.(\d+) (\d+) (\d+)$/;

export function goLines(profile, moduleDirectory) {
  const module = /^module\s+(\S+)/m.exec(readFileSync(join(moduleDirectory, "go.mod"), "utf8"))[1];
  const [mode, ...blocks] = profile.trimEnd().split(/\r?\n/);
  if (!/^mode: (set|count|atomic)$/.test(mode)) throw new Error("Некорректный профиль Go");
  const files = new Map();
  for (const block of blocks) {
    const match = blockPattern.exec(block);
    if (!match || !match[1].startsWith(`${module}/`)) throw new Error(`Некорректный блок Go: ${block}`);
    const [, filename, first, firstColumn, last, lastColumn, statements, count] = match;
    if (Number(statements) === 0) continue;
    if (!files.has(filename)) {
      const source = readFileSync(join(moduleDirectory, filename.slice(module.length + 1)), "utf8");
      files.set(filename, { source: source.split(/\r?\n/), lines: new Map() });
    }
    const { source, lines } = files.get(filename);
    for (let number = Number(first); number <= Number(last); number++) {
      let line = Buffer.from(source[number - 1], "utf8");
      if (number === Number(last)) line = line.subarray(0, Number(lastColumn) - 1);
      if (number === Number(first)) line = line.subarray(Number(firstColumn) - 1);
      if (/^(?:\/\/.*|[{}(),;]*\s*)$/.test(line.toString().trim())) continue;
      // Условие и его тело могут попадать на одну строку. Любой выполненный блок
      // покрывает эту строку, а повторяющиеся блоки не увеличивают знаменатель.
      lines.set(number, Boolean(lines.get(number)) || Number(count) > 0);
    }
  }
  const result = { covered: 0, total: 0 };
  for (const { lines } of files.values()) {
    result.total += lines.size;
    result.covered += [...lines.values()].filter(Boolean).length;
  }
  return result;
}

export function coverageReport(components) {
  const rows = [
    "# Покрытие прикладного кода (Q1)", "",
    "| Компонент | Покрыто строк | Всего строк | Покрытие |",
    "|---|---:|---:|---:|",
  ];
  const percent = (covered, total) => `${(100 * covered / total).toFixed(2)}%`;
  let covered = 0;
  let total = 0;
  for (const [name, counts] of Object.entries(components)) {
    if (!Number.isInteger(counts.covered) || !Number.isInteger(counts.total) ||
        counts.covered < 0 || counts.total <= 0 || counts.covered > counts.total) {
      throw new Error(`Некорректные числа покрытия для ${name}`);
    }
    covered += counts.covered;
    total += counts.total;
    rows.push(`| ${name} | ${counts.covered} | ${counts.total} | ${percent(counts.covered, counts.total)} |`);
  }
  rows.push(`| **Итого** | **${covered}** | **${total}** | **${percent(covered, total)}** |`, "");
  const passed = covered * 5 > total * 4;
  rows.push(passed ? "Порог >80% пройден." : "Порог >80% не пройден.", "");
  return { markdown: rows.join("\n"), passed };
}
