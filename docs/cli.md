# 命令列參考（`kf`）

所有指令都有 `--help`。訊息預設是繁體中文；設定環境變數 `KARAFORGE_LANG=en` 會改成英文。
出錯時會印出「發生什麼事」與「可以怎麼做」；加上 `--verbose`（`-v`）可以看到技術細節。結束代碼：0 成功，1 失敗。

## 最常用的三種用法

```bash
# 一行完成：媒體 + 歌詞 → KTV 影片
kf auto song.mp3 lyrics.txt -o song-ktv.mp4

# 分步驟：建立專案 → 處理 → （在編輯器微調）→ 匯出
kf new song.mp4 --lyrics lyrics.txt -o my-song.kfproj
kf run my-song.kfproj
kf serve --workspace .          # 開瀏覽器到 http://127.0.0.1:8765
kf export my-song.kfproj --format mp4

# 一整個資料夾
kf batch ./songs/ --out ./exports/
```

## 指令

### `kf new MEDIA`

建立專案資料夾（預設在媒體檔旁邊，名稱是 `檔名.kfproj`）。媒體檔會以硬連結（不行的話複製）放進專案。

| 選項 | 說明 |
|---|---|
| `--lyrics`, `-l` | 歌詞檔：`.txt`、`.lrc`、`.srt`、`.ass`（格式見 [lyrics-format.md](lyrics-format.md)）。省略的話，處理時用語音辨識產生草稿。 |
| `--output`, `-o` | 專案資料夾 |
| `--language` | 歌曲語言，例如 `zh-TW`（預設）、`zh-CN`、`en`、`ja`、`ko` |
| `--title`, `--artist` | 歌名、歌手（優先於歌詞檔裡寫的） |
| `--force` | 覆寫已存在的專案 |

### `kf run PROJECT`

執行處理管線到「對齊完成」：讀取媒體 → 分離人聲與伴奏 → 分析 → 語音辨識 →（沒有歌詞時：產生草稿）→ 對齊。
每個階段都有快取：輸入沒變就不會重算，所以重跑很快，中斷後再跑會從中斷的階段繼續。

| 選項 | 說明 |
|---|---|
| `--profile`, `-p` | 處理品質：`cpu-lite`、`balanced`（預設）、`gpu-quality`，見 [profiles.md](profiles.md) |
| `--from STAGE` | 從這個階段起強制重算（`ingest`、`separate`、`analyze`、`asr`、`draft`、`align`） |
| `--set KEY=VALUE` | 覆寫設定檔裡的一個參數，可重複。例如 `--set align.aligner=whisper-attn`、`--set align.onset_snap_ms=80` |

### `kf align PROJECT`

只重新對齊（需要先跑過 `kf run`）。**鎖定的字不會被移動，而且會當成錨點**——在編輯器修正幾個字再重新對齊，附近的字會跟著變準。

| 選項 | 說明 |
|---|---|
| `--respect-locked`／`--ignore-locked` | 保留鎖定的字（預設）／先解除所有鎖定、整首重來（上一版留在 `project.json.bak`） |
| `--line N` | 只重新對齊第 N 行（從 1 起算），可重複 |
| `--profile`、`--set` | 同 `kf run` |

### `kf export PROJECT`

| 選項 | 說明 |
|---|---|
| `--format`, `-f` | `mp4`（預設）、`mkv`、`ass`、`lrc`、`elrc`、`srt`、`ultrastar`、`kfproj` |
| `--audio` | 影片的聲音：`instrumental`（伴奏，預設）、`original`（原曲）、`guide:-12db`（伴奏 + 降低 12 dB 的導唱；數字可改） |
| `--res` | `480p`、`720p`、`1080p`、`1440p`、`2160p`／`4k`，或 `寬x高`（偶數）。預設用專案的設定（1080p）。 |
| `--background` | `video`（原影片）、`color`（純色）、`image`、`blur`（模糊的原影片） |
| `--output`, `-o` | 另外複製一份到這個路徑。檔案一律會產生在專案的 `exports/` 裡。 |

匯出**不會**重新對齊：它照專案目前的內容輸出（包括你在編輯器裡的修改）。純音訊的專案匯出影片時使用主題的背景色。

### `kf auto MEDIA [LYRICS]`

`kf new` + `kf run` + `kf export` 一次做完。專案資料夾建在輸出檔旁邊（`輸出檔名.kfproj`），所以同一個指令再跑一次只會重做有變動的部分。
選項：`--output`、`--profile`、`--audio`、`--res`、`--language`、`--set`。

### `kf batch FOLDER --out FOLDER`

資料夾裡**同名**的媒體檔與歌詞檔配成一首（`夜空.mp3` + `夜空.txt`）。每首歌的專案放在輸出資料夾裡，所以批次中斷後重跑會接著做。
一首失敗不影響其他首；最後印出結果表並寫入 `batch-report.json`，有失敗時結束代碼為 1。

| 選項 | 說明 |
|---|---|
| `--format`、`--profile`、`--audio`、`--res`、`--language`、`--set` | 同上 |
| `--transcribe`／`--skip-without-lyrics` | 沒有歌詞檔的歌：用語音辨識產生草稿／略過（預設） |
| `--dry-run` | 只列出會配成哪些組合，不處理 |

### `kf serve`

啟動 Web 介面（專案列表、新增精靈、編輯器、匯出）。

| 選項 | 說明 |
|---|---|
| `--workspace`, `-w` | 放專案的資料夾（預設：目前的資料夾；也可以用環境變數 `KARAFORGE_WORKSPACE`） |
| `--host` | 預設 `127.0.0.1`。**伺服器沒有登入機制**，改成 `0.0.0.0` 之前請確定網路環境是可信任的。 |
| `--port` | 預設 8765 |
| `--profile` | 新專案預設的處理品質 |
| `--open` | 啟動後開啟瀏覽器 |

### `kf ruby PROJECT`

產生或移除中文歌詞的自動讀音（注音／拼音），見 [ruby.md](ruby.md)。選項：`--kind zhuyin|pinyin`、`--clear`。

### `kf models list | download | verify`

| 指令 | 說明 |
|---|---|
| `kf models list` | 已知的模型、大小、授權、是否已安裝 |
| `kf models download [ID…] [--profile NAME]` | 下載指定的模型，或某個設定檔需要的全部模型（預設 `balanced`）。可續傳，下載後驗證 SHA-256。非商業授權的模型要加 `--accept-license`。 |
| `kf models verify [ID…]` | 重新計算檢查碼 |

模型放在 `$KARAFORGE_HOME/models/`（預設 `~/.local/share/karaforge/models/`）。下載完成後所有功能都可以離線使用。

### `kf doctor`

檢查環境：Python、ffmpeg（是否含 libass 與必要的編碼器）、選用的 yt-dlp、模型會跑在 CPU 還是 GPU、字型與主題、資料目錄的可用空間、各設定檔還缺哪些模型。
`--json` 輸出機器可讀的結果，`--no-models` 略過模型檢查。只有出現「✗」的項目時結束代碼才是 1。

### `kf bench`

執行對齊評測並產生報告，見 [benchmark.md](benchmark.md)。需要從原始碼安裝評測相依套件（`uv sync --extra cpu --group bench`）。

## 環境變數

| 變數 | 作用 |
|---|---|
| `KARAFORGE_HOME` | 模型、使用者主題、使用者字型的位置（預設 `~/.local/share/karaforge`） |
| `KARAFORGE_WORKSPACE` | `kf serve` 的預設工作區 |
| `KARAFORGE_LANG` | 訊息語言：`zh`（預設）或 `en` |
| `KARAFORGE_DEVICE` | `cpu`、`cuda`、`mps`：覆寫自動選擇的運算裝置 |
| `KARAFORGE_THREADS` | 模型推論使用的 CPU 執行緒數（預設：核心數，最多 8） |
| `KARAFORGE_OFFLINE` | 設為 `1` 時不嘗試下載任何東西；缺少模型會直接報錯 |
| `KARAFORGE_ACCEPT_LICENSES` | 以逗號分隔的模型 id：同意它們的非商業授權（等同 `kf models download --accept-license`） |
| `KARAFORGE_FFMPEG`、`KARAFORGE_FFPROBE` | ffmpeg／ffprobe 執行檔的路徑（預設從 `PATH` 找） |
| `KARAFORGE_YTDLP` | yt-dlp 執行檔的路徑（預設從 `PATH` 找；只有用影片網址建立專案時需要） |
| `KARAFORGE_WEB_DIST` | 前端打包結果的位置（開發用） |
