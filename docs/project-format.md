# 專案格式（`.kfproj` 與 `project.json`）

一個 KaraForge 專案就是一個資料夾，慣例以 `.kfproj` 結尾。裡面的 `project.json` 是**唯一的事實來源**：
CLI、Web 編輯器、排版、匯出讀寫的都是它。其餘的檔案不是媒體，就是可以重新算出來的快取。

機器可讀的定義在 [`project.schema.json`](project.schema.json)（JSON Schema，由程式裡的模型自動產生，測試會檢查兩者一致）。
這份文件是給人看的說明。

## 資料夾結構

```text
my-song.kfproj/
├── project.json          # 專案文件（本文說明的對象）
├── project.json.bak      # 上一次儲存的版本
├── media/
│   ├── source.mp4        # 原始媒體（建立專案時複製或硬連結進來）
│   ├── audio.wav         # 抽出來的音訊（48 kHz 立體聲 WAV）
│   ├── vocals.wav        # 分離出的人聲
│   └── instrumental.wav  # 分離出的伴奏
├── cache/                # 各處理階段的快取：可以整個刪掉，下次處理會重算
│   ├── ingest/<key>/ …
│   ├── separate/<key>/ …
│   └── …
└── exports/              # 匯出的檔案
```

把資料夾整個搬走、備份、壓縮都可以；路徑在 `project.json` 裡都是相對於專案資料夾的。
`kf export --format kfproj` 會打包成不含快取的 zip。

## 基本約定

- **時間一律是整數毫秒。**
- **行沒有自己的起迄時間**，一律由行內的字推導。
- 字的 `start_ms`、`end_ms` 都是 `null` 表示「還沒對齊」；兩者必須同時有或同時沒有。
- `locked: true` 的字**不會被任何自動處理更動**（重新對齊、位移以外的批次操作…），而且重新對齊時會當成錨點。
- 把一行所有字的 `text` 接起來，就是那一行的原文（標點與空白附在前一個字的 `text` 裡）。
- 不認得的欄位會被拒絕（避免打錯字或舊格式默默通過）。

## 欄位

```jsonc
{
  "schema_version": 3,        // 格式版本，見下方「版本與遷移」
  "revision": 42,             // 每儲存一次加一；編輯器用它偵測「別處改過了」

  "meta": {
    "title": "夜空中的旅人",
    "artist": "示範樂團",
    "lyricist": "",
    "composer": "",
    "language": "zh-TW",      // 影響語音辨識、繁簡轉換、注音或拼音、片頭卡的用語
    "duration_ms": 215000,
    "lyrics_source": "user"   // "asr" 表示歌詞是語音辨識產生的草稿
  },

  "media": {
    "source": "media/source.mp4",
    "audio": "media/audio.wav",
    "vocals": "media/vocals.wav",
    "instrumental": "media/instrumental.wav",
    "has_video": true
  },

  "analysis": {
    "tempo_bpm": 92.0,                     // 倒數提示依拍點消失；UltraStar 匯出也用它
    "beats_ms": [],
    "vocal_regions": [[1200, 15800]]       // 有人聲的區段
  },

  "singers": [
    { "id": "m",   "label": "男", "theme_slot": "male" },
    { "id": "f",   "label": "女", "theme_slot": "female" },
    { "id": "all", "label": "合", "theme_slot": "duet" }
  ],

  "lines": [
    {
      "id": "L001",                        // 專案內唯一
      "singer": "m",                       // singers 裡的 id
      "paragraph": 0,                      // 第幾段（歌詞檔裡的空行分段）
      "time_hint": [15000, 18200],         // 匯入的檔案或語音辨識給的「這一行大概在哪」；可以是 null
      "tokens": [
        {
          "text": "我",                    // 一個中文字或一個英文單字，連同附著的標點與空白
          "start_ms": 15230,
          "end_ms": 15610,
          "ruby": "ㄨㄛˇ",                 // 讀音（注音、拼音或任何文字）；可以是 null
          "ruby_source": "auto",           // "auto"：自動產生；"manual"：使用者指定
          "confidence": 0.93,              // 0–1，對齊的信心度；編輯器把低於 0.5 的字標出來
          "locked": false,
          "source": "auto"                 // "auto"：對齊器；"manual"：使用者；"import"：匯入檔案的逐字時間
        }
      ]
    }
  ],

  "style": {
    "theme": "classic-ktv",                // 主題名稱（內建或使用者自訂）
    "overrides": { "font.size": 96 }       // 只對這個專案生效的調整，鍵是主題欄位的點號路徑
  },

  "render": {
    "resolution": [1920, 1080],            // 偶數
    "fps": 30,
    "background": { "type": "video" }      // "video"、"image"（加 "image" 路徑）、"color"（加 "color"）、"blur"
  }
}
```

補充：

- `time_hint` 不是這一行的時間，只是給對齊器的線索；`end` 可以是 `null`（LRC 只有開始時間）。
- `confidence` 綜合了三個來源：對齊器自己的分數、粗對齊的品質、以及字的開頭是否落在聲音的起音點上（細節見 [alignment.md](alignment.md)）。
- 行內的字應該依時間排序（格式本身不強制，但對齊、編輯器與排版都假設如此，也都會維持這個順序）；相鄰的字之間可以有空隙（停頓），`end_ms` 也可以等於下一個字的 `start_ms`。
- `style.overrides` 的值會用主題的規則驗證；寫了不存在的鍵會報錯。

## 版本與遷移

`schema_version` 目前是 **3**。

| 版本 | 變更 |
|---|---|
| 1 | 規格書定義的格式 |
| 2 | 每一行多了 `time_hint`；字的 `source` 多了 `"import"` |
| 3 | `meta.lyrics_source` |

- 開啟舊版本的專案時會**在記憶體中**自動升級；檔案要到下一次儲存才會寫成新版，而且儲存前的檔案會留在 `project.json.bak`。
- 比程式還新的版本會被拒絕，並提示更新 KaraForge——不會嘗試硬讀。
- 遷移是「版本 N 的 JSON → 版本 N+1 的 JSON」的純函式（`engine/karaforge/project/migrations.py`），
  有測試固定住規格書裡的 v1 範例能一路升到最新版。

## 並行與安全

- 儲存是原子的（先寫暫存檔再換名），不會留下寫到一半的 `project.json`。
- 帶著 `revision` 儲存：如果磁碟上的 `revision` 已經不是你讀到的那個，儲存會被拒絕（Web API 回 409）。
  編輯器因此不會蓋掉另一個視窗或背景工作的修改。
- 壞掉的 `project.json`（不是合法的 JSON、或不符合格式）會得到說明原因的錯誤訊息，並提示 `.bak` 的存在；不會被自動「修復」。
