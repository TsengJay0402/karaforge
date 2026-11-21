# 更新紀錄

格式參考 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號依 [語意化版本](https://semver.org/lang/zh-TW/)。

## [0.1.0] - 2026-11-21

第一個版本。驗證範圍、完整的評測數據與已知限制見 [`REPORT.md`](REPORT.md)。

### 引擎

- **專案格式**：一個資料夾（`.kfproj`）加一份 `project.json`（格式版本 3，附 JSON Schema 與從 v1、v2 的遷移），原子儲存、revision 衝突偵測、上一版備份。
- **處理管線**：`ingest → separate → analyze → asr → (draft) → align → subtitles → export`，另有 `pitch`。每個階段以輸入內容的雜湊做快取，參數不變就不重算；可取消、有進度。
- **人聲分離**：`audio-separator`（UVR MDX-Net 伴唱型模型，和聲留在伴奏裡）。
- **語音辨識**：`faster-whisper`（tiny 到 large-v3-turbo）。
- **三段式對齊**：行層級錨定（歌詞與辨識結果以羅馬拼音做模糊比對）→ 行內逐字強制對齊 → 精修（起音點吸附、補救沒有證據的字、長音、結束時間），每個字附信心度。
- **對齊器**：`ctc`（wav2vec2 中文 + 英文，預設）、`whisper-attn`、`qwen`（Qwen3-ForcedAligner，選用套件）、`hybrid`、`ctc-mms`（非商業授權，需明確同意）。
- **錨點重對齊**：鎖定的字不會被更動，並作為錨點；緊鄰錨點的字會連同錨點一起對齊。
- **沒有歌詞的流程**：語音辨識 → 歌詞草稿（去除非演唱內容、繁簡轉換、依停頓切行）→ 對齊。
- **注音／拼音**：中文歌詞自動標讀音（含破音字的詞語與虛詞規則、臺灣讀音表），手動讀音優先。
- **KTV 排版引擎**：雙行交替、由左至右連外框一起填色、倒數提示、演唱者配色（含上下雙色合唱）、依真實字寬斷行、片頭資訊卡、讀音；輸出可序列化的算繪計畫。
- **ASS 產生器**：兩層加 `\clip` 的外框填色；同一份 ASS 用於瀏覽器預覽與 ffmpeg 匯出。
- **匯出**：MP4（燒錄字幕）、MKV（軟字幕 + 伴唱／原唱雙音軌 + 內嵌字型）、ASS、LRC、enhanced LRC、SRT、UltraStar（含音高）、專案壓縮檔。
- **匯入**：純文字、LRC（逐行與逐字）、SRT、ASS／SSA。
- **模型管理**：註冊表釘住版本與 SHA-256，可續傳下載與驗證；三個處理品質設定檔 `cpu-lite`／`balanced`／`gpu-quality`。
- 四套主題、三套開放授權字型。

### 命令列

`kf new`、`run`、`align`、`export`、`auto`、`batch`、`serve`、`ruby`、`models list|download|verify`、`doctor`、`bench`。
所有錯誤都有中英文訊息與建議的下一步。

### Web 應用

- 專案列表、新增精靈（上傳媒體、貼上或上傳歌詞、或以語音辨識產生草稿）、處理進度（SSE、可取消）。
- 編輯器：與匯出一致的 JASSUB 預覽、歌詞面板（改字、演唱者、讀音、依信心度上色）、可拖曳的時間軸（波形或頻譜圖、起音點吸附）、
  打點模式、重新對齊（整首或選取的行）、時間位移、復原／重做、自動儲存與衝突偵測、主題編輯器、匯出。
- 介面語言：繁體中文、英文。

### 評測

- 合成歌聲測資產生器（語音合成 + 聲碼器 + 合成伴奏；中、英、混合 × 四種訊噪比），dev／test 分組，
  `kf bench`（消融實驗、錨點實驗、對齊器比較）。結果在 [`docs/benchmark-report.md`](docs/benchmark-report.md)。
- 破音字測試集（171 句）與量測腳本，結果在 [`docs/ruby.md`](docs/ruby.md)。

### 授權

- 以 `uv sync` 安裝的執行環境、Docker 映像與打包後的前端不含 GPL 或非商業授權的程式：間接相依 `diffq`（CC-BY-NC）、`soynlp`（GPL-3.0）、
  `rvfc-polyfill`（GPL-3.0）都用不到，已排除。`scripts/scan_licenses.py` 與對應的單元測試會在這類套件再出現時失敗。
  排除對 `pip install` 無效；評測工具（開發用）會安裝 GPL 套件。見 [`docs/LICENSES.md`](docs/LICENSES.md) 與 ADR 0012。

### 已知限制

見 [`REPORT.md`](REPORT.md) 的第 3、4 節與各文件的對應章節。最重要的幾項：

- 所有準確度數字都來自**合成**歌聲，真實歌曲上沒有量測過。
- GPU（CUDA／MPS）、硬體編碼、macOS、Windows 都沒有實測。
- 中英混合歌詞的對齊明顯比單一語言差。
