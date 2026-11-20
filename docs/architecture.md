# 架構

KaraForge 把「歌曲 + 歌詞 → KTV 影片」拆成一串可以各自重跑的階段，中間的一切都記在一份 `project.json` 裡。
這份文件說明各部分怎麼分工、資料怎麼流動，以及幾個貫穿全專案的設計原則。重要決定的來龍去脈在 [`adr/`](adr/)。

## 一張圖

```text
                    ┌──────────────────────────── 引擎（Python，engine/karaforge） ────────────────────────────┐
 媒體檔 ─┐          │                                                                                          │
 歌詞檔 ─┼─► project │  ingest ─► separate ─► analyze ─┐                                                        │
（或沒有）│  .json   │     │          │                 ├─► (draft) ─► align ─► subtitles ─► export ─► mp4/mkv   │
         │          │     │          └─► asr ──────────┘                 │                                     │
         │          │     │          └─► pitch ─────────────────────────────────────────► ultrastar            │
         │          │  ▲ 每個階段：輸入的內容雜湊 → 快取；輸出發布到 media/ 與 project.json                     │
         │          └──┼───────────────────────────────────────────────────────────────────────────────────────┘
         │             │
         │   ┌─────────┴─────────┐          ┌───────────────────────────────┐
         └──►│ CLI（kf）          │          │ Web（FastAPI + React）         │
             │ new/run/export/…  │◄────────►│ 列表、精靈、編輯器、預覽、匯出 │
             └───────────────────┘  同一份   └───────────────────────────────┘
                                   project.json
```

CLI 與 Web 是同一個引擎的兩個外殼；它們之間沒有私下的狀態，共用的只有專案資料夾。

## 目錄

| 路徑 | 內容 |
|---|---|
| `engine/karaforge/project/` | `project.json` 的模型（Pydantic）、格式遷移、原子儲存與 revision、建立專案、需要文字規則的編輯操作 |
| `engine/karaforge/pipeline/` | 階段的基底類別、執行器（相依順序、快取、進度、取消）、處理品質設定檔 |
| `engine/karaforge/stages/` | 九個階段：`ingest`、`separate`、`pitch`、`analyze`、`asr`、`draft`、`align`、`subtitles`、`export` |
| `engine/karaforge/adapters/` | 模型的轉接層：分離器、語音辨識器、對齊器的 Protocol 與實作、依設定檔建立 adapter 的註冊表 |
| `engine/karaforge/align/` | 對齊演算法本身（特徵、粗對齊、細對齊、精修、信心度、歌詞草稿、CTC 動態規劃）——**不依賴任何模型** |
| `engine/karaforge/text/` | 斷字、羅馬拼音化、繁簡轉換、注音與拼音 |
| `engine/karaforge/layout/` | 字型量測、主題、KTV 排版引擎 → 「算繪計畫」 |
| `engine/karaforge/ass/` | 算繪計畫 → ASS 字幕 |
| `engine/karaforge/io/` | 歌詞的匯入（txt、LRC、SRT、ASS）與匯出（LRC、SRT、UltraStar、影片、專案壓縮檔） |
| `engine/karaforge/models/` | 模型註冊表（版本、檢查碼、授權）、下載（續傳、驗證）、安裝狀態 |
| `engine/karaforge/server/` | FastAPI 應用、工作佇列、事件匯流排（SSE）、工作區 |
| `engine/karaforge/tools/` | ffmpeg／ffprobe 的尋找、能力偵測、執行（進度與取消） |
| `engine/karaforge/cli.py` | `kf` 指令；每個指令都是引擎函式的薄包裝 |
| `web/` | 前端：React + TypeScript；編輯邏輯、時間軸、JASSUB 預覽 |
| `bench/kfbench/` | 合成評測資料產生器、評測執行器、指標、報告、調校工具 |
| `themes/`、`fonts/` | 內建主題與字型（打包時放進 wheel） |
| `tests/` | 單元、整合（真實模型）、視覺（算繪後檢查像素）測試與 fixtures |
| `docker/` | Dockerfile、compose、ffmpeg 的 Docker 包裝腳本 |

## 階段與快取

每個階段（`pipeline/stage.py` 的 `Stage`）宣告三件事：

- `inputs(ctx)`：**決定輸出的所有東西**——輸入檔案（以內容雜湊，而不是路徑或修改時間）、參數、用到的 adapter 的「名稱@版本」、以及專案裡相關的資料（例如歌詞文字與鎖定的錨點）。
- `run(ctx, out_dir)`：把結果寫進一個暫存資料夾。
- `publish(ctx, out_dir, result)`：把（可能來自快取的）結果公開——連結到 `media/`、寫進 `project.json`。

執行器把 `inputs` 加上階段版本雜湊成快取鍵。資料夾 `cache/<階段>/<鍵>/` 已經存在就直接 `publish`，不重算；
不存在就在 `…​.partial-<pid>` 裡執行，成功後才換名，所以中斷不會留下看似完整的半成品。

這帶來幾個性質：

- **參數不變就不重算。** 改了對齊參數只會重跑 `align` 之後的階段；換了歌詞的一個字，`separate`（最慢的階段）不受影響。
- **可重現。** 快取鍵包含 adapter 版本與演算法版本；升級模型或演算法會自然失效。
- **可以放心刪除。** `cache/` 是衍生資料，刪掉只是下次要重算。
- **匯出不會偷偷重新對齊。** 匯出只執行 `subtitles` 與 `export` 兩個階段本身（不帶上游），所以輸出的一定是專案當下的內容。

`draft` 是條件階段：只有專案沒有歌詞時才執行（`is_needed`）。

詳見 [ADR 0004](adr/0004-pipeline-cache.md)。

## 模型都在 adapter 後面

引擎不直接呼叫任何模型函式庫。三種角色各有一個 Protocol（`adapters/base.py`）：

| 角色 | Protocol | 內建實作 |
|---|---|---|
| 分離人聲與伴奏 | `Separator` | `audio-separator`（UVR MDX-Net 伴唱型模型） |
| 語音辨識（逐詞時間） | `Transcriber` | `faster-whisper` |
| 強制對齊 | `Aligner` | `ctc`（wav2vec2 中文 + 英文）、`whisper-attn`、`qwen`、`hybrid`、`ctc-mms` |

每個 adapter 都要自我描述（名稱、版本、權重的授權、支援的語言與裝置、大約的記憶體用量、需要哪些模型）。
重的函式庫在 adapter 內部才匯入、模型在第一次用到時才載入，所以列出設定、`kf models list`、啟動 Web 伺服器都不必等模型。
怎麼加一個新的：見 [adapters.md](adapters.md)。

## 預覽與匯出是同一條路

```text
project.json ─► layout（算繪計畫）─► ass（ASS 文字）─┬─► JASSUB（瀏覽器，libass 的 WebAssembly 版）
                                                     └─► ffmpeg 的 ass 濾鏡（libass）
```

排版引擎是純 Python：用真實字型（HarfBuzz）量每個字的寬度，決定每一行在哪一排、什麼時候出現與消失、
填色在哪一毫秒走到哪一個像素、倒數圓點與片頭卡。輸出是一份可以序列化的「算繪計畫」（方便寫 golden test），
ASS 產生器再把它翻成絕對定位的 ASS。瀏覽器與 ffmpeg 用的是**同一份 ASS、同一個算繪器（libass）、同樣的字型檔**，
所以預覽與輸出的差異只剩下縮放。端對端測試會把兩者的畫面拿來比對（`web/e2e/video.spec.ts`）。

## Web 應用

- 後端：FastAPI。工作區是一個放 `.kfproj` 的資料夾；一次只執行一個工作（單一工作執行緒 + 佇列）；
  進度與「專案被改了」透過 SSE 推送；儲存要帶 revision，衝突回 409。
- 前端：編輯邏輯是對文件的純函式，復原／重做用 immer 的 patch；播放以音訊為主時鐘；時間軸是自己畫的 canvas。

設計理由與沒有採用的做法在 [ADR 0009](adr/0009-web-app-architecture.md)。

## 貫穿全專案的原則

1. **Local-first。** 模型下載完之後不需要網路；沒有遙測，沒有帳號。
2. **`project.json` 是唯一的事實來源。** 任何工具做的修改，其他工具都看得到；人也讀得懂、改得動。
3. **鎖定的字是使用者的決定。** 任何自動處理都不會更動 `locked` 的字，而且會把它們當成錨點。
4. **錯誤要能讓人採取行動。** 每個錯誤都有中英文訊息與建議的下一步（`errors.py`）；技術細節另外放，`--verbose` 才顯示。
5. **不假裝。** 需要模型或 ffmpeg 而環境沒有的測試會被標記並跳過（而且報告會列出），不會用假的輸出冒充；
   評測的門檻不會為了通過而放寬（[benchmark.md](benchmark.md)）。
6. **型別完整。** Python 以 pyright strict 檢查，TypeScript 以 strict 加上 `noUncheckedIndexedAccess`。
