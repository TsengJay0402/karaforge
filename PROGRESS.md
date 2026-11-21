# KaraForge 開發進度

> 依規格 §12 持續維護。最新狀態在最上面；每個里程碑的驗收結果記錄在對應段落。
> 完整的總結（評測數據、驗證清單、已知限制）在 [`REPORT.md`](REPORT.md)。

## 目前狀態（2026-11-21，v0.1.0）

全部里程碑的工作已經結束：M0–M5 完成，M6 大部分完成。剩下沒有做到的事都列在 `REPORT.md` 第 1 節與第 3.2 節，最重要的幾項：

- 所有準確度數字都來自合成歌聲；真實歌曲沒有量過。
- GPU（CUDA、MPS）、macOS、Windows、硬體編碼沒有實測；CI workflow 從未在 GitHub 上執行。
- 錨點重對齊在修正後不再有害，但幫助有限。
- 沒有做系統性的效能調校與錯誤情境稽核。
- 授權：預設安裝與打包的前端原本含有非商業授權與 GPL 的間接相依，M6 最後才發現並排除；排除對 `pip install` 無效（ADR 0012）。

## 里程碑

| 里程碑 | 狀態 | 備註 |
|---|---|---|
| M0 骨架 | 完成 | |
| M1 引擎核心 | 完成 | |
| M2 對齊品質 | 完成 | §10.4 四項目標達成；錨點的缺陷與修正見下方 |
| M3 KTV 排版與輸出 | 完成 | |
| M4 Web App | 完成 | Playwright 14 個加真實模型完整流程 1 個通過 |
| M5 進階功能 | 完成 | 破音字準確率、草稿錯誤率如實報告 |
| M6 打磨與發佈 | 大部分完成 | Docker CPU 映像實測、文件、示範、從零安裝實測、授權掃描與排除、v0.1.0；效能調校與錯誤稽核沒有系統性地做 |

## 驗收紀錄

### M6（2026-11-21）

驗收標準：依 README 從零安裝可以跑通；REPORT.md 完成。

- **從零安裝**（做了兩次，第二次在 commit `48c1dae`）：全新 clone → `uv sync --extra cpu` → 啟用虛擬環境 → 建置前端 →
  `kf doctor`（空的資料目錄）→ `kf models download --profile cpu-lite`（2 分 6 秒）→ `kf auto`（59 秒，產出 720p MP4）→
  `kf serve`（健康檢查、網頁、專案列表）。全部成功。
  第一次發現 README 原本寫的 `uv run kf …` 會把 CPU 版 PyTorch 換成 CUDA 版，已改成先啟用虛擬環境。
- **Docker（CPU）**：第一次建置失敗（`diffq` 需要 C 編譯器）。先加編譯器讓它過，之後發現 `diffq` 是非商業授權而且根本用不到，
  改成排除，編譯器也拿掉。最後的映像（3.65 GB，commit `48c1dae`）：容器內 `kf doctor`、`kf models download --profile cpu-lite`（全新 volume）、
  `kf auto`（非預設使用者 id、bind mount，52 秒）；`docker compose up` 後健康檢查、網頁、專案列表與字幕算繪器的檔案正常。hadolint 通過。
  同時修正了 compose 的專案資料夾路徑與使用者 id 的問題。
- **Docker（CUDA）**：建置成功（13 GB），在沒有 GPU 的機器上可以啟動並退回 CPU；沒有在有 GPU 的機器上執行過。驗證後映像已刪除。
- **授權**：掃描整個環境後排除三個用不到的間接相依——`diffq`（CC-BY-NC）、`soynlp`（GPL-3.0）、前端的 `rvfc-polyfill`（GPL-3.0）；
  每一個都在移除後實際跑過相關流程。新增 `scripts/scan_licenses.py` 與對應的單元測試、前端的建置檢查。經過與剩下的例外在 `REPORT.md` 第 7 節與 ADR 0012。
- **全新 clone 上的測試**（`v0.1.0` 的內容）：Python 3.12.3 與 3.11.18 都是 795 通過、2 略過（需要評測工具）、8 個需要模型的未選取。
- **完整測試**：`pytest --cov` 805 通過，引擎覆蓋率 93%；Vitest 70；Playwright 14 + 真實模型完整流程 1。
- 示範歌曲、長歌與草稿錯誤率這幾個一次性的量測改成可以重做：`scripts/compare_with_truth.py`、`scripts/join_songs.py`（附測試，
  其中一個測試直接核對 `examples/README.md` 引用的數字）。草稿錯誤率因此以完整流程重量，文件已更新。
- `gpu-quality` 設定檔在 CPU 上完整跑過（示範歌曲：中位數 13 ms、最大 141 ms）。
- 示範檔案在 `examples/demo/`；文件完成；`REPORT.md` 完成；版號 0.1.0，標籤 `v0.1.0`。

### M5（2026-11-21）

驗收標準：各功能都有測試；破音字準確率如實報告。

- `kf doctor`、`kf align --respect-locked`、`kf batch`：單元測試加上真實執行（`kf batch` 兩首完成、一首略過）。
- 無歌詞流程：`draft` 階段、專案格式第 3 版。真實模型的整合測試 3 個通過。草稿的字元錯誤率（一首合成歌曲）：`cpu-lite` 83.7%；當時另外直接執行辨識器量到 small 53.5%、large-v3-turbo 48.8%，
  發佈前改成以完整流程重量，`balanced` 51.2%、`gpu-quality` 60.5%（文件採用這一組）。
- 注音／拼音：破音字測試集 171 句（先於引擎提交），準確率 92.4%（158/171），未加自訂規則的基準 88.3%；讀錯的 13 題沒有針對性修改。
- UltraStar 音高、模型管理（`kf models list|download|verify`，11 個模型全部通過檢查碼驗證）。

### M4（2026-11-21）

驗收標準：Playwright 端對端測試通過；預覽與匯出畫面一致。

- Playwright（Chromium，對真正的伺服器）14 個測試通過，包含在實際播放中打點、時間軸拖曳、主題另存、讀音，以及
  **預覽對匯出的影格比對**（同一時間點，已唱與未唱顏色的範圍相差 < 1% 畫面寬）。
- 規格 §11 的完整流程（建立專案 → 處理 → 拖曳修改一個字 → 重新對齊 → 匯出 → 檢查輸出檔）以真實模型執行通過。
  第一次執行時失敗，揭露兩個編輯器的問題（暫停時時間軸不會捲到選取的字；相鄰兩字交界處的拖曳對象不確定），都已修正。
- 只在 Chromium 上驗證。

### M3（2026-11-21）

驗收標準：golden tests 與視覺迴歸測試通過；所有格式往返測試通過。

- 排版引擎與 ASS 的 golden test、15 個視覺迴歸測試（算繪後抽樣像素，含外框）通過。
- LRC、enhanced LRC、SRT、ASS、UltraStar 的往返測試通過（`tests/unit/test_formats.py`）。
- MKV：軟字幕、伴唱與原唱兩條音軌（有標題與預設旗標）、內嵌字型，以 ffprobe 檢查；沒有在實體播放器上看過。
- 後來補上的規則：歌詞換段時較短的停頓就清空畫面並倒數（每行都空一行的歌詞除外）。

### M2（2026-11-21）

驗收標準：評測報告產出；誠實比對第 10.4 節目標。

- test 分組完整矩陣（120 個音檔 × 12 種設定）：`docs/benchmark-report.md`。目標格（`balanced`、中文、10 dB）：
  中位數 11 ms、P95 86 ms、需修正 2.8%、鎖定 5% 隨機錨點後 4.2%（第 7 版）／3.0%（第 8 版）——四項都達成。
- **評測揭露的缺陷**：第 7 版鎖定錨點後其餘的字變差（同一批字 6.5% → 7.7%）。凍結前沒有在 dev 上跑過錨點實驗，是流程上的疏漏。
  只用 dev 分組找出原因並修正（演算法第 8 版，ADR 0011），重測為 6.5% → 6.1%；中文仍是持平到略差。重測報告：`docs/benchmark-report-anchors.md`。
- 其他如實記錄的發現：預設對齊器不是最準的（非商業授權的 `ctc-mms` 較好）；「一行一個時間窗」對 CTC 沒有量到好處；
  中英混合歌詞約一成需要修正；`whisper-attn` 約兩成。

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
- `audio-separator` 在正規化重疊視窗時會印出一個 `RuntimeWarning: invalid value encountered in divide`（視窗邊緣的 0/0）。
  那些樣本會被它自己裁掉；實際檢查過分離出來的音軌沒有非有限值，也沒有接縫處的爆音。
- 授權上的排除（`diffq`、`soynlp`）只對 uv 有效；評測工具會安裝 GPL 套件（見 `docs/LICENSES.md`）。
- `gpu-quality` 在同一首歌上有一次執行的結果與其他四次略有不同（當時機器負載很高），原因沒有查明。

## 工作紀錄

### 2026-11-21

- M2：CTC／Qwen／hybrid 對齊器與評測工具在 commit `ac5bfce` 凍結，test 分組完整評測；評測揭露錨點處理的缺陷，
  在 dev 上修正（演算法第 8 版）後重測。ADR 0006–0008、0011。
- M3 收尾：MKV 雙音軌、LRC／SRT／ASS／UltraStar 的匯入匯出、專案格式第 2 版。
- M4：FastAPI 伺服器、工作佇列、SSE；前端全部頁面與編輯器（canvas 時間軸、JASSUB 預覽、主題面板）；
  Vitest 與 Playwright 測試；預覽對匯出的影格比對。ADR 0009。
- M5：`kf doctor`、`kf align`、`kf batch`；無歌詞流程（`draft` 階段、專案格式第 3 版）；注音／拼音與破音字測試集。ADR 0010。
- M6：文件、範例、Docker 映像實際建置與執行、依 README 從零安裝、Python 3.11 測試、全形標點、相依套件授權的掃描與排除（ADR 0012）、
  v0.1.0、REPORT.md。
- 外包給 GLM 的單元測試：`batch`、`doctor`、繁簡轉換、歌詞草稿四個檔案，逐檔審閱並執行；`doctor` 的測試有一個錯誤的 import 與一個錯誤的預期值。
- 只有實際執行才發現的問題（都已修正）：Docker 建置失敗進而揭露的授權問題、`uv lock` 因為無法建置的 `diffq-fixed` 而失敗、
  `uv run` 會換掉 PyTorch、compose 的路徑與使用者 id、CUDA 映像上 `kf doctor` 的錯誤提示、
  全新 clone 上兩個需要評測工具的測試、時間軸的兩個互動問題、Whisper 的無語音判斷吃掉前 30 秒。

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
