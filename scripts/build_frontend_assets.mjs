import { cp, copyFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const copy = async (source, destination) => {
  await mkdir(dirname(destination), { recursive: true });
  await copyFile(resolve(root, source), resolve(root, destination));
};

await mkdir(resolve(root, 'static/vendor/webfonts'), { recursive: true });
await copy('node_modules/@fortawesome/fontawesome-free/css/all.min.css', 'static/vendor/fontawesome/all.min.css');
await cp('node_modules/@fortawesome/fontawesome-free/webfonts', 'static/vendor/webfonts', { recursive: true });
await copy('node_modules/chart.js/dist/chart.umd.min.js', 'static/vendor/chart.umd.min.js');

for (const family of ['dm-sans', 'space-grotesk']) {
  const weights = family === 'dm-sans' ? [400, 500, 600, 700] : [500, 600, 700];
  for (const weight of weights) {
    await copy(
      `node_modules/@fontsource/${family}/files/${family}-latin-${weight}-normal.woff2`,
      `static/vendor/fonts/${family}-latin-${weight}-normal.woff2`,
    );
  }
}

const metricUtilities = Array.from({ length: 101 }, (_, value) =>
  `.metric-width-${value}{width:${value}%}.metric-donut-${value}{--metric-percent:${value}%}`,
).join('');
await writeFile(
  resolve(root, 'static/css/metrics.css'),
  `.risk-donut{--metric-color:#EF4444}.performance-donut{--metric-color:#4F46E5}` +
    `.risk-donut,.performance-donut{background:conic-gradient(var(--metric-color) var(--metric-percent,0%),#E2E8F0 0)}` +
    metricUtilities,
);
