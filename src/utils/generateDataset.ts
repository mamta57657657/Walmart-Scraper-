import fs from 'node:fs';
import path from 'node:path';
import { generateFullDataset } from './dataset';

const allRecords = generateFullDataset();
const outputDir = path.resolve('public', 'data');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}
const outputPath = path.join(outputDir, 'walmart_scraped_products_500.json');
fs.writeFileSync(outputPath, JSON.stringify(allRecords, null, 2), 'utf-8');
console.log(`Generated ${allRecords.length} records to ${outputPath}`);
