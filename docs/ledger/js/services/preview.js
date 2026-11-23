// 預覽版專用：放入範例資料、清空資料。
import * as db from '../storage/db.js';
import { DEFAULT_CATEGORIES } from '../defaults.js';
import { buildSample } from '../sample.js';
import { todayStr } from '../domain/format.js';

/** 第一次開啟、而且還沒有任何紀錄時，放入範例資料 */
export async function loadSampleOnce() {
  if ((await db.get('meta', 'sampleLoaded'))?.value) return false;
  const hasData = (await db.getAll('transactions')).length > 0;
  if (!hasData) await db.replaceAll(buildSample(todayStr(), db.uid));
  await db.put('meta', { key: 'sampleLoaded', value: true });
  return !hasData;
}

export const loadSample = () => db.replaceAll(buildSample(todayStr(), db.uid));

/** 清空全部紀錄、預算、固定收支，類別恢復預設 */
export const clearAllData = () => db.replaceAll({ categories: DEFAULT_CATEGORIES });
