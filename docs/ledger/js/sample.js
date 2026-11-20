// 範例資料（預覽版第一次開啟時使用）。純函式：同一天產生的內容都一樣。
import { DEFAULT_CATEGORIES } from './defaults.js';
import { addMonths, monthOf, monthRange, pad2 } from './domain/format.js';

// 可重現的亂數
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const FOOD = [
  ['早餐 蛋餅豆漿', 65, 95], ['午餐 便當', 90, 140], ['晚餐 拉麵', 220, 320],
  ['手搖飲', 50, 75], ['超商', 45, 160], ['晚餐 自助餐', 95, 150], ['咖啡', 60, 150],
];
const TRANSPORT = [['捷運', 25, 60], ['公車', 15, 30], ['Uber', 180, 360]];
const OTHER = [['日用品', 180, 650], ['衛生紙、洗衣精', 260, 520], ['電影票', 300, 360], ['手機配件', 390, 990]];
const SOCIAL = [['朋友聚餐', 600, 1400], ['同事生日禮物', 500, 1000], ['喜帖紅包', 1600, 3600]];

/**
 * 產生 today 所在月份往前共 3 個月的範例資料。
 * 房租、薪水用固定收支規則表示，開啟 App 時由 generateDue() 自動記入。
 */
export function buildSample(today, uid) {
  const r = rng(Number(today.replaceAll('-', '')));
  const pick = (list) => list[Math.floor(r() * list.length)];
  const amount = ([, lo, hi]) => Math.round((lo + r() * (hi - lo)) / 5) * 5;

  const transactions = [];
  let seq = 0;
  const add = (date, categoryId, item) => {
    seq += 1;
    transactions.push({
      id: uid(), type: 'expense', amount: amount(item), categoryId, date, note: item[0],
      createdAt: Date.parse(`${date}T12:00:00`) + seq, updatedAt: Date.parse(`${date}T12:00:00`) + seq,
    });
  };

  const start = addMonths(monthOf(today), -2);
  for (let m = start; m <= monthOf(today); m = addMonths(m, 1)) {
    const lastDay = Number(monthRange(m)[1].slice(8));
    for (let d = 1; d <= lastDay; d++) {
      const date = `${m}-${pad2(d)}`;
      if (date > today) break;
      const meals = 1 + Math.floor(r() * 3);
      for (let i = 0; i < meals; i++) add(date, 'food', pick(FOOD));
      if (r() < 0.55) add(date, 'transport', pick(TRANSPORT));
      if (r() < 0.07) add(date, 'other_expense', pick(OTHER));
      if (r() < 0.05) add(date, 'social', pick(SOCIAL));
    }
    const gasDay = `${m}-18`;
    if (gasDay <= today) add(gasDay, 'transport', ['加油', 1100, 1400]);
    const billDay = `${m}-12`;
    if (billDay <= today) add(billDay, 'housing', ['水電瓦斯', 900, 1600]);
  }

  const rule = (o) => ({ id: uid(), note: '', active: true, startMonth: start, lastGenerated: null, ...o });
  const recurring = [
    rule({ type: 'expense', amount: 15000, categoryId: 'housing', note: '房租', day: 5 }),
    rule({ type: 'income', amount: 52000, categoryId: 'salary', note: '薪水', day: 5 }),
    rule({ type: 'expense', amount: 390, categoryId: 'other_expense', note: '影音訂閱', day: 20 }),
  ];

  const budgets = [
    { id: 'total', amount: 32000 },
    { id: 'food', amount: 8000 },
    { id: 'social', amount: 3000 },
  ];

  return { categories: DEFAULT_CATEGORIES, transactions, budgets, recurring };
}
