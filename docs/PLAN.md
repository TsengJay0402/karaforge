# KaraForge 開發計畫

> 依 `docs/SPEC.md` 拆解。這是開工時的計畫；實際進度與偏離記錄在根目錄的 `PROGRESS.md`，
> 重大決策寫在 `docs/adr/`。

## 1. 整體策略

1. **先打通一條最細的端到端路徑，再逐層加厚。** M1 結束時就要能從音檔＋歌詞產出會填色的 MP4，
   之後每個里程碑都在可執行的系統上改進，而不是最後才整合。
2. **評測先於調校。** 合成測資產生器在 M1 就做出最小版本（M1 的驗收需要它），M2 開始前把產生器定稿、
   固定 seed，並切成 `dev`（調參數用）與 `test`（只用來出報告）兩組，避免對著測試集調參。
3. **引擎是純函式庫。** CLI 與 Server 都只是薄薄一層；所有邏輯都能在沒有網頁、沒有伺服器的情況下測試。
4. **模型一律走 adapter，並且用真模型驗證。** 單元測試可以用明確命名的測試替身（`Fake*`）驗證演算法邏輯，
   但評測數字、整合測試、示範影片一律來自真實模型；兩者在報告中分開列。
5. **預覽與匯出同源。** 排版只在 Python 做一次，輸出 ASS；瀏覽器（JASSUB）與 ffmpeg 都吃同一份 ASS。

## 2. 架構決策摘要（細節見各 ADR）

| 主題 | 決定 | ADR |
|---|---|---|
| 套件結構 | 單一發佈套件 `karaforge`，原始碼在 `engine/karaforge`；評測套件 `kfbench` 在 `bench/`，一起打包 | 0001 |
| ffmpeg 來源 | 依序找環境變數 → `PATH` → `$KARAFORGE_HOME/bin`；本機用 Docker 包裝的 Debian ffmpeg | 0002 |
| Token 模型 | 標點與空白附著在 token 文字上；尚未對齊的時間為 `null`；匯入的行層級時間放在 `time_hint` | 0003 |
| 管線快取 | 每個階段的輸出存到 `cache/<stage>/<key>/`，再「發佈」到 `media/` 與 `project.json`；鍵＝輸入內容雜湊＋參數＋adapter 版本＋階段版本 | 0004 |
| PyTorch 安裝 | 預設 PyPI 版；`--extra cpu`／`--extra cuda` 切換 wheel 來源 | 0005 |
| 對齊器 | 實測後決定各設定檔的預設（候選：CTC wav2vec2、Whisper cross-attention、Qwen3-ForcedAligner） | 0006 |
| 合成測資 | TTS 逐字合成＋聲碼器改音高與時長＋numpy 伴奏；dev／test 分組 | 0007 |
| 時間軸 | 自製 Canvas 時間軸（60fps、上千個 token 區塊） | 0008 |
| 外框填色 | 兩層事件＋串接的 `\t(\clip)`，未唱層用 `\iclip` 互補 | 0009 |
| 工作排程 | 伺服器行程內的單一 worker 佇列＋SSE 廣播 | 0010 |

## 3. 里程碑拆解

### M0 骨架
- [ ] `docs/ENVIRONMENT.md`、`docs/PLAN.md`、`docs/SPEC.md`
- [ ] `pyproject.toml`（uv、hatchling、ruff、pyright strict、pytest＋coverage）、套件骨架、`kf --version`
- [ ] 錯誤類別（雙語訊息）、設定與路徑（`KARAFORGE_HOME`）、ffmpeg 探測
- [ ] `web/`：Vite＋React＋TS strict＋ESLint＋Vitest 腳手架
- [ ] GitHub Actions workflow、Dockerfile 初版、Makefile、README 初版、`PROGRESS.md`
- 驗收：`uv run pytest`、`npm test` 通過；ruff、pyright、tsc、eslint 零錯誤

### M1 引擎核心
- [ ] `project/`：Pydantic schema、JSON Schema 匯出、遷移框架、原子寫入與 revision
- [ ] 歌詞 txt parser 與 tokenizer（中文逐字、英文逐詞、混合、`字{讀音}`、演唱者標記、metadata）
- [ ] `pipeline/`：Stage 介面、DAG、內容雜湊快取、進度、取消
- [ ] `stages/ingest`：ffprobe、轉 48k 立體聲、`peaks.json`
- [ ] `adapters/separators`：`audio-separator`（UVR）
- [ ] 基本對齊：ASR（faster-whisper）＋一種 aligner，逐行對齊
- [ ] 基本 layout＋ASS（已含兩層 clip 填色）＋MP4 匯出
- [ ] CLI：`new`／`run`／`export`／`auto`
- [ ] 合成測資最小版（一首歌）供驗收
- 驗收：`kf auto` 產出可播放且會填色的 MP4（抽影格檢查像素）；第二次執行全部命中快取

### M2 對齊品質
- [ ] 前處理：VAD（能量＋頻譜特徵、可選 Silero）、tempo／beats、onset（spectral flux）
- [ ] 粗對齊：ASR 字元層級模糊比對、行時間窗、VAD 比例分配的退路
- [ ] 細對齊：`Aligner` Protocol；至少兩種實作（CTC、Whisper cross-attention），嘗試 Qwen3-ForcedAligner
- [ ] 精修：onset 吸附、單調性、最短字長、結束時間、行尾長音
- [ ] 信心度、錨點重對齊
- [ ] `bench/synth` 定稿（每語言 ≥10 首、4 種 SNR、dev／test 分組）、指標、`kf bench`（消融、錨點實驗）
- 驗收：報告產出，數字如實對照 §10.4

### M3 KTV 排版與輸出
- [ ] 字型量測（uharfbuzz＋fontTools，與 libass 的字級換算一致）
- [ ] layout 全部規則：雙行交替、斷行、倒數、片頭卡、ruby、演唱者配色（含雙色合唱）
- [ ] 主題 YAML 與 ≥3 套內建主題、內建 OFL 字型
- [ ] 匯出：MP4 各種音訊／背景模式、MKV 雙音軌＋附加字型、ASS、LRC、增強型 LRC、SRT、UltraStar、zip
- [ ] 匯入：LRC、增強型 LRC、ASS
- [ ] golden tests、視覺迴歸測試（含外框像素）、往返測試
- 驗收：以上測試通過

### M4 Web App
- [ ] FastAPI：專案 CRUD、媒體 Range 串流、preview.ass、jobs、SSE、exports、主題、字型
- [ ] Job runner：佇列、取消、進度
- [ ] 前端：專案列表、新增精靈、處理進度、編輯器（預覽／歌詞面板／時間軸／打點／重新對齊／批次調整／復原重做／自動儲存／快捷鍵）、主題編輯器、匯出頁、繁中與英文
- [ ] Playwright 端對端；預覽 vs 匯出的同時間點畫面比對
- 驗收：端對端測試通過；畫面比對結果如實記錄

### M5 進階功能
- [ ] 無歌詞流程（ASR 草稿 → 編輯 → 對齊）
- [ ] G2P：注音／拼音、破音字；自建 ≥50 句測試集並報告準確率
- [ ] UltraStar 音高（pYIN）、`kf batch`、`kf doctor`、`kf models`（下載續傳＋checksum）
- 驗收：各功能有測試；破音字準確率如實報告

### M6 打磨與發佈
- [ ] Docker `cpu`／`cuda` 映像、compose、healthcheck、非 root、hadolint
- [ ] 效能調校、錯誤處理全面檢查
- [ ] 文件：README（繁中／英文）、架構、格式規格、演算法、主題、adapter 指南、LICENSES、ADR
- [ ] `examples/` 示範專案與影片、CHANGELOG、v0.1.0、`REPORT.md`
- 驗收：照 README 從零安裝跑通（在乾淨的容器裡驗證）

## 4. 風險與對策

| # | 風險 | 可能性 | 影響 | 對策 |
|---|---|---|---|---|
| R1 | 沒有 GPU，CUDA 路徑無法實測 | 確定 | 中 | 程式走同一套 adapter；裝置選擇邏輯寫單元測試；報告明確列為未驗證 |
| R2 | 對齊器在「歌聲」上不準（模型都是用語音訓練的） | 高 | 高 | 三段式演算法本來就是為此設計；以多種 aligner 實測比較；信心度＋錨點重對齊作為半自動的補救；數字不達標就如實報告 |
| R3 | TTS 合成的「歌」跟真歌差很多，評測失真 | 高 | 中 | 用聲碼器做音高與長音而非單純 time-stretch；另外提供 `bench/real`；在報告中說明合成測資的侷限 |
| R4 | 對著測資調參造成過度擬合 | 中 | 高 | dev／test 分組；測資產生器在調參前定稿並記錄版本；任何產生器的修改都寫進 PROGRESS |
| R5 | uharfbuzz 量測與 libass 實際算繪的字寬不一致 → 填色邊界錯位 | 中 | 高 | 複製 libass 的字級換算（OS/2 winAscent＋winDescent）；用影格量測校驗；視覺迴歸測試把關 |
| R6 | JASSUB（WASM libass）與 ffmpeg 的 libass 版本不同，畫面有差 | 中 | 中 | 同一份 ASS、同一批字型檔；量測差異並設定合理門檻，如實報告 |
| R7 | 模型授權不相容（例如 MMS 是 CC-BY-NC） | 中 | 中 | 預設只用寬鬆授權的權重；其餘改成使用者自行下載並明確提示；`docs/LICENSES.md` 完整列出 |
| R8 | 大型模型在 CPU 上太慢 | 中 | 中 | 設定檔分級；逐行時間窗讓對齊成本與歌長成線性；模型只載入一次 |
| R9 | 背景負載造成資源波動，效能數字不穩 | 中 | 低 | 限制執行緒；處理時間取多次中位數並註明環境 |
| R10 | 規格範圍很大，後段里程碑被壓縮 | 中 | 高 | 每個里程碑先做完整的最小版本並 commit；PROGRESS 誠實標記部分完成 |
| R11 | ffmpeg 透過 Docker 包裝，行為與原生有差（訊號、路徑） | 低 | 中 | 引擎一律用工作目錄內的相對檔名、`-nostdin`；取消時送 SIGTERM；Docker 映像內用原生 ffmpeg 再驗一次 |
| R12 | 第三方套件 API 與我的認知不同（例如 Qwen3 系列、JASSUB 新版） | 中 | 中 | 動手前先查官方文件與套件原始碼，不憑記憶寫 |

## 5. 品質門檻（每個里程碑結束都要過）

- `ruff check`、`ruff format --check`、`pyright`（strict）零錯誤
- `pytest` 全部通過；需要模型權重的測試以 marker 區分
- 前端 `tsc --noEmit`、`eslint`、`vitest` 零錯誤
- `PROGRESS.md` 更新、git commit
