# KaraForge 開發進度

> 依規格 §12 持續維護。最新狀態在最上面；每個里程碑的驗收結果記錄在對應段落。

## 目前狀態（2026-11-21 04:40，工作因用量上限再次中斷時的實際狀態）

**已完成並實際驗證過**

- **M2**：test 分組完整評測（120 個音檔 × 12 種設定）跑完。規格 §10.4 四項目標全部達成（中文 10 dB：中位數 11 ms、P95 86 ms、
  需修正 2.8%、鎖定 5% 隨機錨點後 3.0%）。評測同時揭露「錨點反而讓其餘的字變差」的缺陷，已在 dev 上找出原因並修正（演算法第 8 版），
  再於 test 上重測；完整經過與所有不好看的數字都寫在 `docs/benchmark.md`。原始報告：`docs/benchmark-report.md`（第 7 版、完整矩陣）、
  `docs/benchmark-report-anchors.md`（第 8 版、錨點），原始資料在 `bench/reports/`。
- **M3**：排版、ASS、MKV 雙音軌、各種匯入匯出（先前已完成）；單元 755、整合與視覺 37 個測試在本次修改後重新執行通過。
- **M4**：Web App 完成。Vitest 69 個通過；Playwright 14 個（不含需要模型的那一個）在 03:24 通過，包含預覽對匯出的影格比對。
- **M5**：`kf doctor`、`kf align --respect-locked`、`kf batch`、無歌詞流程（真實模型的整合測試 3 個通過；草稿的字元錯誤率如實量測：
  `cpu-lite` 83.7%，最好的模型約 49%）、注音／拼音（破音字測試集 171 句，準確率 92.4%，未經調整的基準 88.3%，見 `docs/ruby.md`）。
- **文件**：README（中、英）、cli、lyrics-format、project-format、themes、profiles、architecture、adapters、ruby、LICENSES、
  alignment、benchmark、ADR 0001–0009、CHANGELOG（草稿）。

**寫好了但還沒有執行或驗證（不要當成已完成）**

- 03:24 之後的修改（換段規則、介面標點、讀音面板以外的調整、無提示辨識的設定）之後，**Playwright 沒有重跑**。
- `web/e2e/process.spec.ts`（真實模型：上傳 → 處理 → 拖曳 → 重新對齊 → 匯出 → 檢查檔案，規格 §11 要求的那一條）**從來沒有執行過**。
  執行方式：`cd web && KARAFORGE_E2E_MODELS=1 npm run e2e -- process`。
- `docker/Dockerfile` 與 `docker/docker-compose.yml`：hadolint 通過、`docker compose config` 通過，**映像沒有建置過**（CPU 與 CUDA 都沒有）。
- CI workflow 沒有在 GitHub 上跑過；Python 3.11 沒有實際跑過測試。

**還沒做**

- `REPORT.md`（最終報告）。
- `examples/`（示範專案、MP4、MKV）與 README 用的影片截圖。
- 版號改成 0.1.0 並打 tag；依 README 從零安裝的實測；覆蓋率與程式碼行數的統計。
- 引擎訊息（CLI／伺服器）的全形標點整理：腳本在 `.tmp/fullwidth_py.py`（未套用；需要略過三引號字串並處理一個 LRC 格式說明的特例）。
- 硬體編碼器選項沒有開放成設定；分離階段的細部進度沒有做。

## 里程碑

| 里程碑 | 狀態 | 備註 |
|---|---|---|
| M0 骨架 | 完成 | |
| M1 引擎核心 | 完成 | |
| M2 對齊品質 | 完成 | 目標達成；錨點的效果有限，如實記錄 |
| M3 KTV 排版與輸出 | 完成 | |
| M4 Web App | 大致完成 | 需要模型的端對端測試尚未執行；最新修改後 Playwright 未重跑 |
| M5 進階功能 | 完成 | 各功能有測試；準確率如實報告 |
| M6 打磨與發佈 | 未完成 | 文件完成；Docker 建置、示範影片、REPORT.md、版號、從零安裝驗證未做 |

## 驗收紀錄

### M1（2026-11-20）

驗收標準：`kf auto` 在合成測資上產出可播放、字幕會填色的 MP4；快取命中時不重算。

實際執行並通過：

- `kf auto bench/_data/probe/zh-2000/mix_snr10.wav lyrics.txt -o out.mp4 --res 720p`（`balanced` 設定檔，真實模型）：
  48.5 秒的合成歌曲，第一次 58 秒完成（分離 27.5 s、辨識 6.3 s、對齊 5.3 s、輸出 7.0 s）；
  輸出為 H.264 1280x720 30fps + AAC 48 kHz 立體聲，長度 48.5 s。
- 同一行指令再跑一次：7 個階段全部命中快取，2.9 秒結束。
- 抽影格目視確認：雙行交替、片頭卡、倒數點、唱過的字「本體與外框」一起變色。
- 自動化測試（`pytest`，418 passed，engine 覆蓋率 94%）：
  - `tests/integration/test_full_pipeline.py`（真實模型，`cpu-lite`）：`kf auto` 產出影片、每個 token 都有時間且單調、
    影片影格中已唱顏色的像素數隨時間增加、第二次執行 7 個階段都是快取、鎖定 token 後重新對齊不會改到 locked token。
  - `tests/visual/test_fill_pixels.py`（15 個）：以 ffmpeg + libass 算繪後抽樣像素，驗證填色邊界與時間軸一致（±2.5 px）、
    外框與本體在同一位置變色、排版量測的寬度與 libass 實際畫出來的一致（三套字型）、雙色合唱、以及實際匯出的 MP4。
  - `tests/integration/test_media_pipeline.py`：ingest（影片／單聲道音檔／無音訊／損毀檔）、三種音訊模式的匯出、匯出不會觸發重新對齊。
- `ruff check`、`ruff format --check`、`pyright`（strict，含 tests）：零錯誤。

注意事項（如實記錄）：

- 第一輪數字**不是評測結果**：在單一首開發用合成歌上，`balanced`（whisper-small + Whisper 注意力對齊器）
  起始時間誤差中位數約 70–80 ms、>150 ms 的比例約 23–28%，離 §10.4 的目標還很遠。M2 會加入 CTC 對齊器並用完整測資評測。
- 合成測資產生器還沒定稿（M2 開始調對齊之前會定稿並記錄版本）。
- M1 提前做了屬於 M3 的部分：排版引擎（雙行交替、斷行、倒數、片頭卡、ruby、字型 fallback）、
  兩層 clip 的外框填色 ASS、4 套主題、視覺迴歸測試。M3 還缺：MKV、LRC／SRT／UltraStar 匯出、LRC／ASS 匯入。

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
- `audio-separator` 0.48 少宣告了 `audioread` 相依，而且啟動時一定要在 `PATH` 找到 ffmpeg；兩者都已在本專案繞過
  （補上相依、adapter 會把找到的 ffmpeg 目錄加進 `PATH`）。
- `faster-whisper` 1.2.1 自己的檔案解碼與目前的 PyAV 不相容；本專案一律先自行解碼成 16 kHz 陣列再交給它，不受影響。
- 分離階段的進度目前以 30 秒為一段回報（每段之間可以取消），段內沒有更細的進度。
- 日文假名與韓文目前只有基本的羅馬拼音（供比對與對齊用），沒有經過評測。

## 工作紀錄

### 2026-11-20

- M1：project schema／遷移／store、歌詞 txt parser 與 tokenizer、Pipeline DAG 與內容雜湊快取、模型註冊表與可續傳下載、
  ingest／separate／analyze／asr／align／subtitles／export 各階段、UVR 分離與 faster-whisper adapter、
  Whisper 交叉注意力對齊器、三段式對齊的 coarse／fine／refine／confidence、排版引擎、ASS 產生器、MP4 匯出、
  CLI `new／run／export／auto／models`、合成測資產生器初版（Kokoro TTS + WORLD 聲碼器 + numpy 伴奏）。
- 把機械性的單元測試交給 GLM 起草兩批（共 13 個測試檔），逐檔審閱、修正後納入：
  第一批 95 個測試有 8 個是測試本身寫錯，另外揭露了一個真的 bug（Big5 檔在位元組數為偶數時被誤判成 UTF-16）；
  第二批 111 個測試有 1 個寫錯。
- 視覺測試揭露並修正了排版量測與 libass 不一致的問題：libass 預設不做字距微調（kerning），
  而且只要字距（letter spacing）不為零就會關閉 kerning 與連字；現在 ASS 明確寫入 `Kerning: yes`，量測也照同樣規則。
- 產生器在評測前修正了一個會讓測資「太簡單」的問題：連音（legato）的字之間原本會掉到無聲，現在改成真的重疊交叉淡化。
- ADR 0003（token 模型）、0004（管線快取）、0005（PyTorch 安裝來源）。

### 2026-11-19

- 偵測環境並寫入 `docs/ENVIRONMENT.md`；規格存成 `docs/SPEC.md`；計畫寫入 `docs/PLAN.md`。
- 安裝 uv（使用者層級）；下載靜態 ffmpeg 的做法被權限機制擋下，改用 Docker 包裝的 Debian ffmpeg。
- M0：`pyproject.toml`（uv／hatchling／ruff／pyright strict／pytest）、套件骨架（errors、runtime、paths、
  tools.ffmpeg、i18n、cli）、前端腳手架（Vite 8／React 19／TS 6 strict／ESLint 10／Vitest 5）、
  CI workflow、Makefile、ADR 0001–0002。
