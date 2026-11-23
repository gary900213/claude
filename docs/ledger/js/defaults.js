// 預設類別：第一次開啟 App 時寫入資料庫。
// id 固定不變，之後改名、換圖示都不影響既有紀錄。
const EXPENSE = [
  { id: 'food', name: '餐飲', icon: '🍱' },
  { id: 'transport', name: '交通', icon: '🚌' },
  { id: 'housing', name: '居住', icon: '🏠' },
  { id: 'social', name: '人情交際', icon: '🎁' },
  { id: 'other_expense', name: '其他支出', icon: '📦' },
];

const INCOME = [
  { id: 'salary', name: '薪資', icon: '💼' },
  { id: 'bonus', name: '獎金', icon: '🎉' },
  { id: 'side_income', name: '兼職外快', icon: '🧰' },
  { id: 'investment', name: '投資收益', icon: '📈' },
  { id: 'other_income', name: '其他收入', icon: '💰' },
];

export const DEFAULT_CATEGORIES = [
  ...EXPENSE.map((c) => ({ ...c, type: 'expense' })),
  ...INCOME.map((c) => ({ ...c, type: 'income' })),
].map((c, i) => ({ ...c, order: i, hidden: false, builtin: true }));
