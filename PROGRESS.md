# KaraForge 開發進度

> 依規格 §12 持續維護。最新狀態在最上面；每個里程碑的驗收結果記錄在對應段落。

## 目前狀態

- **進行中**：M1 引擎核心
- **下一步**：M2 對齊品質

## 里程碑

| 里程碑 | 狀態 | 備註 |
|---|---|---|
| M0 骨架 | 完成 | 驗收見下方 |
| M1 引擎核心 | 進行中 | |
| M2 對齊品質 | 未開始 | |
| M3 KTV 排版與輸出 | 未開始 | |
| M4 Web App | 未開始 | |
| M5 進階功能 | 未開始 | |
| M6 打磨與發佈 | 未開始 | |

## 驗收紀錄

### M0（2026-11-19）

實際執行並通過：

- `uv sync` 後 `pytest`：15 passed（含 5 個實際呼叫 ffmpeg／ffprobe 的測試，其中 1 個驗證取消會終止行程）
- `ruff check`、`ruff format --check`：零錯誤；`pyright`（strict，含 tests）：0 errors
- `web/`：`npm run typecheck`、`npm run lint`（`--max-warnings 0`）、`npm test`（1 passed）、`npm run build` 全部通過

尚未執行：

- `docker/Dockerfile` 只是初版，還沒實際建置（M6 處理；`--extra cpu|cuda` 要等 M1 加入 PyTorch 相依後才存在）
- GitHub Actions 沒有在 GitHub 上跑過

## 已知問題

- 開發主機沒有 GPU：CUDA／MPS／硬體編碼路徑無法實測（見 `docs/ENVIRONMENT.md`）。
- 開發主機沒有系統 ffmpeg：使用 Docker 包裝的 Debian ffmpeg 7.1.5（見 ADR 0002）。
- GitHub Actions workflow 只能在本機逐步手動執行相同指令驗證，沒有在 GitHub 上實際跑過。

## 工作紀錄

### 2026-11-19

- 偵測環境並寫入 `docs/ENVIRONMENT.md`；規格存成 `docs/SPEC.md`；計畫寫入 `docs/PLAN.md`。
- 安裝 uv（使用者層級）；下載靜態 ffmpeg 的做法被權限機制擋下，改用 Docker 包裝的 Debian ffmpeg。
- M0：`pyproject.toml`（uv／hatchling／ruff／pyright strict／pytest）、套件骨架（errors、runtime、paths、
  tools.ffmpeg、i18n、cli）、前端腳手架（Vite 8／React 19／TS 6 strict／ESLint 10／Vitest 5）、
  CI workflow、Makefile、ADR 0001–0002。
