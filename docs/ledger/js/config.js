// 執行環境設定。
// PREVIEW = true 是預覽版（單一 HTML 檔）用的：
// 第一次開啟會放入範例資料、不註冊離線快取、匯出改成提示（預覽頁不能下載檔案）。
// 正式網站維持 false；打包預覽版時由 tools/build_ledger.mjs 用 esbuild 的 define 把它設成 true。
/* global __LEDGER_PREVIEW__ */
export const PREVIEW = typeof __LEDGER_PREVIEW__ !== 'undefined' && __LEDGER_PREVIEW__ === true;

/** 版本：每次更新程式時改成當天日期，設定頁會顯示，方便確認手機上跑的是哪一版 */
export const APP_VERSION = '2026.11.25';
