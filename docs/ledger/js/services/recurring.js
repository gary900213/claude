// 固定收支：規則的增刪改，以及開啟 App 時自動產生到期的紀錄。
import * as db from '../storage/db.js';
import { validateRecurring, ValidationError } from '../domain/validate.js';
import { generateFor } from '../domain/recurring.js';
import { todayStr } from '../domain/format.js';

export async function listRules() {
  const rules = await db.getAll('recurring');
  return rules.sort((a, b) => a.day - b.day || a.amount - b.amount);
}

export const getRule = (id) => db.get('recurring', id);

export async function saveRule(id, input) {
  const v = validateRecurring(input, await db.getAll('categories'));
  if (!v.ok) throw new ValidationError(v.errors);
  const cur = id ? await db.get('recurring', id) : null;
  if (id && !cur) throw new Error('找不到這個固定收支');
  // 改了開始月份，就從新的開始月份重新算
  const lastGenerated = cur && cur.startMonth === v.value.startMonth ? cur.lastGenerated : null;
  const rule = { id: cur?.id ?? db.uid(), ...v.value, lastGenerated };
  await db.put('recurring', rule);
  return rule;
}

/** 刪除規則；已經記入的紀錄會保留 */
export const deleteRule = (id) => db.remove('recurring', id);

/**
 * 產生所有到期的紀錄，回傳新增了幾筆。
 * 讀規則、寫紀錄、更新規則在同一個交易裡完成，
 * 同時開兩個分頁也不會重複產生。
 */
export function generateDue(today = todayStr()) {
  return db.run(['recurring', 'transactions'], 'readwrite', (t) => {
    const result = { count: 0 };
    const rules = t.objectStore('recurring');
    const txs = t.objectStore('transactions');
    const req = rules.getAll();
    req.onsuccess = () => {
      for (const rule of req.result) {
        const out = generateFor(rule, today, { uid: db.uid });
        if (!out.transactions.length) continue;
        for (const tx of out.transactions) txs.put(tx);
        rules.put(out.rule);
        result.count += out.transactions.length;
      }
    };
    return result;
  }).then((r) => r.count);
}
