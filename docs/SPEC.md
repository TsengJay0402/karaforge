# KaraForge — 開源 KTV 影片產生器：完整開發規格與任務指令

> 這份文件是交給你（開發 Agent）的完整任務。請從頭讀到尾再開始動手。

---

## 0. 給 Agent 的總指示

你是一位資深的全端工程師，同時精通音訊訊號處理與語音 ML。你要**從零獨立完成**一個可發佈的開源專案 KaraForge。

- 這是長時間、多里程碑的自主開發任務。**不要問我問題**，持續工作直到所有里程碑完成，或確實無法再前進為止。
- 規格沒寫到的地方，自行做出最合理的工程決策，並寫成 ADR（`docs/adr/NNNN-標題.md`：背景、選項、決定、後果）。
- 規格中標示「必須」的是硬性要求；標示「建議」的可以換成更好的方案，但要寫 ADR 說明理由。
- 誠實比好看重要：做不到的就說做不到，不准造假（詳見第 12 節）。

### 開工前三件事
1. **偵測環境**，結果寫進 `docs/ENVIRONMENT.md`：作業系統、CPU/RAM、Python 與 Node 版本、ffmpeg 是否有 libass、能否執行 Docker daemon、有無 CUDA/MPS、能否連網（PyPI、npm、Hugging Face 分別測）。
2. **寫 `docs/PLAN.md`**：依本規格拆解任務、列出風險與對策、每個里程碑的預估工作項目。
3. 直接開始 M0，不需等待確認。

---

## 1. 產品定義

**一句話**：匯入影片／音檔＋歌詞，自動對齊到「逐字」，在網頁編輯器裡微調，輸出台灣 KTV 風格的卡拉 OK 影片。

**目標使用者**：想做 KTV 影片的個人與 YouTuber、活動或婚禮主持、小型 KTV 與教會詩歌團隊、語言學習者。

**三條核心流程**
1. **全自動**：音檔（或 MV）＋歌詞 txt → 一行指令 → KTV 影片。
2. **半自動（主力體驗）**：自動對齊後進入網頁編輯器，系統用信心度標出可疑的字；使用者修正幾個關鍵字後按「重新對齊」，其他字以這些修正為錨點自動變準；即時預覽後輸出。
3. **無歌詞**：ASR 產生歌詞草稿 → 人工修正文字 → 對齊 → 輸出。

**明確不做（非目標）**：歌曲或影片下載功能、內建有版權的歌詞庫、雲端多人服務、唱歌評分遊戲（列入未來規劃即可）。

---

## 2. 設計原則（必須遵守）

1. **Local-first**：模型下載完成後，所有功能都能離線運作。
2. **半自動優先**：自動結果永遠可以編輯；用信心度引導使用者注意力；手動修正的內容絕不被自動流程覆蓋。
3. **所見即所得**：編輯器預覽與最終輸出使用**同一個 ASS 檔、同一個 libass 算繪引擎**（瀏覽器端用 libass 的 WASM 版本 JASSUB，匯出端用 ffmpeg + libass），確保預覽與成品一致。
4. **中文優先、多語可用**：中文以「字」為單位對齊與填色；英文以「詞」為單位；中英混合要正確處理。
5. **可插拔、可重現**：所有模型都走 adapter 介面；每個處理階段都有內容雜湊快取，參數不變就不重算。
6. **CPU 可跑、GPU 加速**：預設 CPU 能完成整條流程；有 CUDA 時自動加速。

---

## 3. 系統架構

```
┌──────────────────────── Web App (React + TS) ────────────────────────┐
│  專案列表 │ 新增精靈 │ 處理進度 │ 編輯器（JASSUB 預覽 + 波形時間軸）│ 匯出  │
└───────────────────────────────┬──────────────────────────────────────┘
                     REST + SSE（進度事件）+ Range 媒體串流
┌───────────────────────────────┴──────────────────────────────────────┐
│ FastAPI Server ── Job Runner（佇列、取消、進度回報）                     │
├──────────────────────────────────────────────────────────────────────┤
│ Engine（純 Python 函式庫，CLI 與 Server 共用）                           │
│  ingest → separate → [transcribe] → align → layout → ass → export     │
│  Pipeline DAG ＋ 內容雜湊快取                                            │
├──────────────────────────────────────────────────────────────────────┤
│ Adapters：separators / aligners / asr / g2p / onset                   │
├──────────────────────────────────────────────────────────────────────┤
│ ffmpeg · libass · PyTorch · ONNX Runtime                              │
└──────────────────────────────────────────────────────────────────────┘
```

### 儲存庫結構（建議）
```
karaforge/
├── engine/                 # Python 套件 karaforge
│   └── karaforge/
│       ├── project/        # schema、遷移、讀寫
│       ├── pipeline/       # Stage 介面、DAG、快取、runner
│       ├── stages/         # ingest, separate, transcribe, align, layout, export
│       ├── adapters/       # separators/, aligners/, asr/, g2p/, onset/
│       ├── align/          # 三段式對齊演算法（coarse/fine/refine/confidence）
│       ├── layout/         # KTV 排版引擎、主題、字型量測
│       ├── ass/            # ASS 產生器
│       ├── io/             # importers/ 與 exporters/
│       ├── models/         # 模型註冊表、下載、驗證
│       ├── server/         # FastAPI
│       └── cli.py          # typer
├── web/                    # React + Vite + TypeScript
├── bench/                  # 合成測資產生器、評測指標、評測 runner
├── tests/
├── fonts/                  # 內建開源字型（OFL）
├── themes/                 # 內建主題 YAML
├── docker/
└── docs/
```

### 技術選型（建議）
- Python 3.11+、uv、ruff、pyright（strict）、pytest、Pydantic v2、typer、FastAPI
- 字型排版量測：uharfbuzz + fontTools（真實字寬，不准用估計值）
- 前端：React、Vite、TypeScript（strict）、Zustand、TanStack Query、wavesurfer.js v7 或自製 Canvas 時間軸（選一個並寫 ADR）、JASSUB、Vitest、Playwright
- 內建字型（必須是 OFL 授權）：Noto Sans TC、源泉圓體、jf open 粉圓（KTV 感）

---

## 4. 專案格式

### 4.1 專案資料夾 `*.kfproj/`
```
my-song.kfproj/
├── project.json
├── media/
│   ├── source.mp4            # 原始檔（或 .mp3 等）
│   ├── audio.wav             # 48kHz 立體聲，分析用
│   ├── vocals.wav
│   ├── instrumental.wav
│   └── peaks.json            # 波形峰值，給 UI 快速顯示
├── cache/<stage>/<hash>/      # 各階段快取
└── exports/
```

### 4.2 `project.json`（必須用 Pydantic 定義，並輸出 JSON Schema 到 docs/）
```json
{
  "schema_version": 1,
  "revision": 42,
  "meta": {
    "title": "", "artist": "", "lyricist": "", "composer": "",
    "language": "zh-TW", "duration_ms": 0
  },
  "media": {
    "source": "media/source.mp4", "audio": "media/audio.wav",
    "vocals": "media/vocals.wav", "instrumental": "media/instrumental.wav",
    "has_video": true
  },
  "analysis": { "tempo_bpm": 92.0, "beats_ms": [], "vocal_regions": [[1200, 15800]] },
  "singers": [
    { "id": "m", "label": "男", "theme_slot": "male" },
    { "id": "f", "label": "女", "theme_slot": "female" },
    { "id": "all", "label": "合", "theme_slot": "duet" }
  ],
  "lines": [
    {
      "id": "L001",
      "singer": "m",
      "paragraph": 0,
      "tokens": [
        {
          "text": "我", "start_ms": 15230, "end_ms": 15610,
          "ruby": "ㄨㄛˇ", "ruby_source": "auto",
          "confidence": 0.93, "locked": false, "source": "auto"
        }
      ]
    }
  ],
  "style": { "theme": "classic-ktv", "overrides": {} },
  "render": { "resolution": [1920, 1080], "fps": 30, "background": { "type": "video" } }
}
```

規則：
- 時間一律用整數毫秒。行的開始／結束時間由 tokens 推導，不另外儲存。
- 使用者在編輯器手動改過的 token 自動設為 `locked: true, source: "manual"`。**任何自動流程都不得修改 locked token。**
- `revision` 每次儲存遞增，用來偵測衝突。
- 必須有 schema 版本遷移機制與遷移測試。

### 4.3 歌詞輸入格式（.txt）
```
# title: 歌名
# artist: 歌手
# lyricist: 作詞
# composer: 作曲

[男] 第一句歌詞
[女] 第二句歌詞
[合] 一起唱 together

[男] 空行代表段落分隔，可觸發倒數提示
這句沒有標記，沿用上一句的演唱者
他還是重{ㄔㄨㄥˊ}複了一次
```
- `[男] [女] [合]` 或 `[m] [f] [all]` 標記演唱者，也允許自訂 `[Amy]`。
- `字{注音或拼音}` 手動指定讀音（處理破音字）。
- `#` 開頭的行是 metadata。
- 也必須支援匯入 .lrc、增強型 LRC、.ass 作為起點（保留原本的時間）。

---

## 5. 處理管線

### 5.1 Stage 介面與快取（必須）
- 每個 Stage 宣告輸入、參數、adapter 名稱與版本；快取鍵為 `sha256(輸入檔雜湊 + 參數 + adapter 版本)`。
- Runner 自動解析相依、只重跑受影響的階段，支援進度回報（0–1 加上文字訊息）與取消。
- 錯誤使用自訂例外類別，包含給使用者看的訊息（繁中與英文）和給開發者看的細節。

### 5.2 各階段規格

**① ingest**
- 用 ffprobe 偵測格式；接受 mp4/mkv/mov/webm/mp3/wav/flac/m4a/ogg。
- 轉出 48kHz 立體聲 `audio.wav` 供分析；最終輸出時使用原始音質。
- 產生 `peaks.json`（多種縮放層級）。

**② separate**
- `Separator` Protocol。預設使用 `audio-separator`（UVR 系模型）；備選 Demucs（htdemucs）。
- 建議預設用「karaoke 類」模型，讓和聲保留在伴奏中（比較接近真實 KTV 伴唱帶），並另外產生乾淨的主唱軌供對齊使用。
- 長音檔分段處理，控制記憶體用量。

**③ transcribe（只在沒有歌詞時執行）**
- `Transcriber` Protocol。CPU 預設 faster-whisper；可選 Qwen3-ASR。
- 在 vocals 軌上辨識，輸出歌詞草稿（依停頓切行）與粗略時間。

**④ align — 系統核心，必須實作三段式演算法**

1. **前處理**：在 vocals 軌上偵測人聲活動區段（能量加上頻譜特徵；可選用 Silero VAD）；用 librosa 估計 tempo 與 beats。
2. **粗對齊（行層級錨定）**：在 vocals 上跑帶時間戳的 ASR，用**字元層級模糊比對**（必須能處理沒有空格的中文、容忍 ASR 聽錯）把每一行歌詞對應到時間窗。ASR 品質太差時，退回依人聲活動區段按字數比例分配。目的是避免整首歌一起對齊時誤差越滾越大。
3. **細對齊（字層級）**：每一行在自己的時間窗（前後各留約 1 秒）內做強制對齊。`Aligner` Protocol，建議實作：
   - Qwen3-ForcedAligner（中文首選）
   - CTC 類對齊器（wav2vec2 / MMS，中文先轉拼音再對齊）作為 CPU 輕量備選
   - 至少兩種實作可切換，並在評測中比較
4. **精修**：
   - **onset 吸附**：偵測 vocals 的起音點（spectral flux），把字的開始時間吸附到 ±N ms 內最近的起音點（N 可設定）。
   - 強制單調遞增、最短字長（例如 60ms）。
   - 結束時間：預設等於下一個字的開始；遇到超過門檻的停頓時，改以人聲能量下降點為準。
   - **長音處理**：行尾最後一個字延續到人聲能量消失為止。
5. **信心度**：綜合對齊器分數、粗對齊與細對齊的一致性、onset 吻合程度，算出 0–1 的分數並寫入每個 token。
6. **錨點重對齊（必須）**：locked token 是硬性錨點，只對錨點之間的區段重新對齊。這是半自動體驗的核心：使用者修正 3 個字，其餘自動變準。

**⑤ layout — KTV 排版引擎（必須，純 Python，輸出「算繪計畫」）**

輸入 project 與主題，輸出每一行的 row、座標、逐字字框（用真實字型量測）、ruby 位置、出現／消失時間、填色關鍵影格、倒數事件。排版規則：
- **雙行交替**：第 1 行在上排、靠左；第 2 行在下排、靠右；兩行同時出現。一行唱完後，下一句進入空出來的那一排。進場時間不晚於開唱前 X 秒（主題可設定）。
- **填色**：由左往右填色，**字的外框也要一起變色**；在每個字的時間內線性推進，跨字為分段線性。
- **倒數提示**：一行開唱前的空白超過 N 秒（預設 4 秒）時，在該行起點上方顯示 3 個點，依拍點（有 tempo 時）或固定間隔逐一消失。
- **演唱者配色**：依 singer 的 theme_slot 套色；合唱可設為第三色或雙色。
- **斷行**：每排寬度上限為畫面寬度的某個比例（以真實字寬計算）；優先在標點與空白處斷；不拆英文單字；原始歌詞太長時拆成兩個顯示行，並正確分配時間。
- **片頭資訊卡**：開頭第一句之前顯示歌名、歌手、作詞、作曲（經典 KTV 片頭）。
- **ruby（注音／拼音）**：可開關，顯示在字的上方並置中對齊。
- 排版結果必須可序列化，方便寫 golden test。

**⑥ ass — ASS 產生器（必須）**
- 依算繪計畫產生 ASS；PlayResX/Y 等於輸出解析度；用 `\an7\pos` 絕對定位。
- **外框填色技巧**：Layer 0 放「未唱」樣式的整行文字；Layer 1 放「已唱」樣式的同一行，以 `\clip` 矩形由左往右推進（用串接的 `\t(t1,t2,\clip(...))` 依每個字的時間分段，或拆成多個事件），讓文字本體與外框同時變色。不要只用 `\k` / `\kf`，因為它們不會填外框。
- 倒數點用 `\p` 向量繪圖；片頭卡用獨立事件。
- 同一份 ASS 同時提供給瀏覽器預覽（JASSUB）與 ffmpeg 匯出。

**⑦ export**
- **MP4**：H.264 + AAC，ffmpeg `ass` filter 搭配 `fontsdir` 燒錄字幕。音訊選項：純伴奏／伴奏＋導唱（主唱降低 X dB）／原曲。
- **MKV**：影片＋ASS 軟字幕（附加字型）＋兩條音軌（「伴唱」預設、「原唱」）。
- **背景**：原影片（縮放加補邊）／圖片／純色／模糊封面；可選字幕區底部漸層加暗，提升可讀性。
- **字幕與資料格式**：.ass、.lrc、增強型 LRC（逐字）、.srt、UltraStar .txt（音高用 pYIN 在 vocals 上估計每個 token 的 MIDI 音高）、`.kfproj` 打包成 zip。
- 有支援的硬體編碼器時可選用；預設使用軟體編碼確保相容。

---

## 6. Web App

### 6.1 頁面
1. **專案列表**：縮圖、狀態、最後修改時間。
2. **新增精靈**：拖放媒體檔 → 貼上或上傳歌詞（或勾選「沒有歌詞，用 AI 辨識」）→ 選擇處理品質（快速／平衡／高品質）→ 開始。
3. **處理進度**：各階段即時進度（SSE），可以取消；失敗時顯示可理解的原因與建議。
4. **編輯器**（主力，見下節）。
5. **匯出**：選格式、解析度、音訊模式、背景，並顯示匯出進度。

### 6.2 編輯器（必須）
- **上方：預覽區**：影片或背景加上 JASSUB 渲染的 ASS（與匯出同源）；播放控制；音訊切換：伴唱／原唱／只聽人聲；播放速度 0.5x–1.5x。
- **中間：歌詞面板**：逐行列出，可直接編輯文字、切換演唱者、編輯 ruby；每個字依信心度著色（低信心醒目標示）；點任何一個字就跳到該時間。
- **下方：時間軸**：vocals 波形（可切換頻譜圖）；每個字是可拖曳、可調整左右邊界的區塊；縮放與捲動；播放頭跟隨；可開關「吸附到 onset」。
- **打點模式**：
  - 點擊模式：播放時每按一次空白鍵，標記下一個字的開始。
  - 按住模式：按下＝開始、放開＝結束，最適合 KTV 長音。
- **重新對齊**：以 locked token 為錨點重跑對齊（可只對選取的行）。
- **批次調整**：整首歌全域位移、整行平移、方向鍵以 ±10ms 微調選取的字。
- 文字修改後，用字元 diff 保留仍然對得上的時間。
- 復原／重做（用 immer patches）、debounce 自動儲存、用 revision 偵測衝突。
- 快捷鍵說明面板（按 `?` 開啟）。
- **主題編輯器**：即時調整字型、字級、顏色、外框、位置，可另存成新主題 YAML。
- 介面語言：繁體中文（預設）與英文。

### 6.3 API（建議）
- `GET/POST/PATCH/DELETE /api/projects[/{id}]`
- `POST /api/projects/{id}/jobs`（指定 stages 與參數）、`DELETE /api/jobs/{job_id}`（取消）
- `GET /api/events`（SSE）
- `GET /api/projects/{id}/media/{name}`（支援 HTTP Range）
- `GET /api/projects/{id}/preview.ass`（依目前狀態即時產生）
- `POST /api/projects/{id}/exports`
- 前端打包成靜態檔，由 FastAPI 提供，讓 `kf serve` 一個指令就能用。

---

## 7. CLI（必須）

```
kf new song.mp3 --lyrics lyrics.txt -o my-song.kfproj
kf run my-song.kfproj [--profile cpu-lite|balanced|gpu-quality] [--from align]
kf align my-song.kfproj --respect-locked
kf export my-song.kfproj --format mp4 --audio guide:-12db --res 1080p
kf auto song.mp3 lyrics.txt -o out.mp4        # 全自動一行完成
kf batch ./songs/ --out ./exports/            # 資料夾內同名的音檔與 txt 配對
kf serve [--port 8765]
kf models list|download|verify
kf bench [--suite synthetic|real] [--aligner ...] [--ablation]
kf doctor                                     # 檢查環境與依賴
```

---

## 8. 模型管理與處理品質設定檔

- 模型存放目錄由 `KARAFORGE_HOME` 指定；下載時驗證 checksum，可續傳。
- 每個 adapter 都要宣告：名稱、版本、授權、支援語言、支援裝置、大約記憶體需求。
- 處理品質設定檔：
  - `cpu-lite`：最快的模型組合，CI 與測試使用
  - `balanced`：CPU 上品質與速度兼顧（預設）
  - `gpu-quality`：最佳品質
- 自動偵測 CUDA（以及原生執行時的 Apple MPS），無法使用時自動退回 CPU 並提示。

---

## 9. 部署

- **原生安裝**：`uv sync` 之後即可 `kf serve`；README 說明 ffmpeg（含 libass）的安裝方式。
- **Docker（必須提供）**：
  - 多階段建置：Node 階段建置前端 → Python 執行階段（ffmpeg + libass + 內建字型）。
  - 兩種映像：`cpu` 與 `cuda`。
  - `docker-compose.yml`：volume 掛載專案目錄與模型快取（模型權重**不打包**進映像）；`gpu` profile 啟用 NVIDIA。
  - 非 root 使用者、healthcheck、映像大小控制。
  - README 註明 macOS 上的 Docker 無法使用 Apple GPU，Mac 使用者建議原生安裝。
- 若目前環境無法執行 Docker：用 hadolint 檢查 Dockerfile，並在報告中**明確寫出未實際建置**。

---

## 10. 評測基準（必須，這是最重要的品質證據）

### 10.1 合成測資產生器 `bench/synth/`
因為不能使用有版權的歌曲，請自建可重現（固定 seed）的合成測資：
1. 用離線 TTS（例如 piper、espeak-ng）**逐字或逐詞**合成中文、英文、中英混合歌詞，依已知間隔拼接 → 得到**精確的標準答案時間軸**。
2. 加入歌唱特性：部分字做 time-stretch 製造長音、輕微的 pitch 變化與 vibrato、快速段落、超過 8 秒的長間奏。
3. 用 numpy 合成伴奏（和弦鋪底、bass、鼓點），以 0／5／10／20 dB 訊噪比混音。
4. 規模：每種語言至少 10 首，每首 30–90 秒。

### 10.2 真實歌曲評測（選用，不進版控）
`bench/real/` 讀取使用者自行放入的歌曲與人工校正過的 project.json 作為標準答案。程式與說明文件要完整，資料不提交。

### 10.3 指標
- 每個 token 開始時間的絕對誤差：中位數、P90、P95
- **需人工修正比例**：誤差超過 150ms 的 token 佔比（代表使用者要修多少字）
- 行層級錯配率（token 被對到錯誤的行）
- 各階段在 CPU 上的處理時間與即時倍率
- **消融實驗**（`--ablation`）：分別關閉粗對齊、onset 吸附、長音處理，量化每個階段的貢獻
- **錨點實驗**：隨機 lock 5% 的 token（設為標準答案）後重新對齊，量化半自動修正的效果
- 輸出 Markdown 報告與 JSON 原始數據

### 10.4 目標（`balanced` 設定檔、10 dB 中文測資）
- 中位數誤差 ≤ 60 ms、P95 ≤ 250 ms
- 需人工修正比例 ≤ 10%；lock 5% 錨點後 ≤ 5%

**規則**：不得為了過關而放寬門檻、修改測資或針對測資寫特例。達不到時如實報告數據，並分析原因、提出改進方向。

---

## 11. 品質要求

- **單元測試**：layout 規則、ASS 產生器（golden files）、schema 遷移、各格式 parser 與 writer 的往返測試、模糊比對、onset 吸附、錨點重對齊。
- **整合測試**：以 `cpu-lite` 在合成測資上跑完整條管線。
- **視覺迴歸測試（必須）**：輸出影片後，在指定時間點擷取畫面，抽樣檢查「已唱區域」與「未唱區域」的像素顏色，**包含外框像素**，自動驗證填色進度與時間軸一致。
- **端對端測試**：Playwright 走完「建立專案 → 處理 → 拖曳修改一個字 → 重新對齊 → 匯出 → 檢查輸出檔」。
- engine 測試覆蓋率 ≥ 80%；ruff 與 pyright strict 零錯誤；前端 TypeScript strict、ESLint 零錯誤。
- GitHub Actions：lint、型別檢查、單元測試、整合測試（cpu-lite，快取模型）、前端 build 與測試、Docker build（可用 hadolint 替代並註明）。
- 需要模型權重而環境中沒有的測試，用 pytest marker 標記並跳過，報告中必須列出。

---

## 12. 工作規則

1. 持續維護 `PROGRESS.md`：已完成／進行中／已知問題／下一步。每完成一個有意義的段落就更新。
2. 每個里程碑結束時：跑完全部測試 → 更新文件 → git commit（訊息清楚、一個里程碑可以多個 commit）→ 在 PROGRESS.md 記錄驗收結果。
3. **禁止造假**：
   - 不得用 mock 或寫死的輸出冒充真實模型結果。
   - stub 必須明確 `raise NotImplementedError` 並列在已知問題中。
   - 測試沒實際執行就不能宣稱通過；驗證沒實際做就不能宣稱完成。
4. 遇到問題先自行除錯；同一個問題用三種不同方法仍然失敗時，記錄下來，改走替代方案繼續前進，不要停住。
5. 依賴與模型授權必須相容於 Apache-2.0 的發佈方式；在 `docs/LICENSES.md` 列出所有依賴、模型權重與字型的授權。若某個模型授權不相容，改成「使用者自行下載」並清楚說明。
6. 程式碼：完整型別、函式職責單一、公開 API 都有 docstring、錯誤訊息對使用者友善。
7. 效能：模型只載入一次並重複使用、長音檔分段處理、善用快取、UI 操作保持流暢（時間軸拖曳 60fps）。

---

## 13. 里程碑與驗收

| 里程碑 | 內容 | 驗收標準 |
|---|---|---|
| **M0 骨架** | 儲存庫結構、uv、lint、型別檢查、pytest、前端腳手架、CI、Dockerfile 初版、README 初版、ENVIRONMENT.md、PLAN.md | CI 設定完成；`uv run pytest` 與 `npm test` 通過 |
| **M1 引擎核心** | project schema 與遷移、Pipeline DAG 與快取、ingest、separate、基本對齊（單一 aligner）、基本 ASS、MP4 匯出、CLI `new/run/export/auto` | `kf auto` 在合成測資上產出可播放、字幕會填色的 MP4；快取命中時不重算 |
| **M2 對齊品質** | 三段式對齊、第二種 aligner、信心度、錨點重對齊、合成測資產生器、`kf bench` 含消融與錨點實驗 | 評測報告產出；誠實比對第 10.4 節目標 |
| **M3 KTV 排版與輸出** | layout 引擎全部規則、外框填色 ASS、倒數提示、片頭卡、斷行、3 套以上內建主題、全部匯出格式（MKV 雙音軌、LRC 系列、SRT、UltraStar）、匯入 LRC/ASS | golden tests 與視覺迴歸測試通過；所有格式往返測試通過 |
| **M4 Web App** | FastAPI、Job runner、SSE、全部頁面、編輯器完整功能、JASSUB 預覽、主題編輯器、繁中與英文 | Playwright 端對端測試通過；預覽與匯出畫面一致（擷取同一時間點比對） |
| **M5 進階功能** | ASR 無歌詞流程、注音與拼音及破音字（自建至少 50 句破音字測試集並報告準確率）、UltraStar 音高、批次處理、`kf doctor`、模型管理 | 各功能都有測試；破音字準確率如實報告 |
| **M6 打磨與發佈** | Docker cpu/cuda 映像與 compose、效能調校、錯誤處理全面檢查、完整文件、CHANGELOG、v0.1.0 版號、示範影片（用合成測資） | 依 README 從零安裝可以跑通；REPORT.md 完成 |

---

## 14. 最終交付物

1. 完成全部里程碑的程式碼庫（含 git 歷史）。
2. **README.md**（繁體中文）與 **README.en.md**：特色、截圖或 GIF、原生與 Docker 兩種安裝方式、快速開始、處理品質設定檔建議、常見問題、版權提醒（使用者須自行確認音樂與歌詞的權利）。
3. `docs/`：架構說明、project.json 規格與 JSON Schema、歌詞 txt 格式、對齊演算法說明、主題 YAML 規格、adapter 開發指南（如何新增對齊器、分離器、主題）、LICENSES.md、全部 ADR。
4. `examples/`：用合成測資產出的示範專案、示範 MP4 與 MKV。
5. **REPORT.md**（最終報告）必須包含：
   - 各里程碑狀態（完成／部分完成／未完成，附原因）
   - `kf bench` 完整數據表（含消融與錨點實驗），並與第 10.4 節目標對照
   - **實際執行過的驗證**與**未能執行的驗證**兩份清單（例如 Docker 建置、GPU 測試、需要權重的測試）
   - 已知限制、技術債與建議的下一步
   - 程式碼行數、測試數量、覆蓋率、CI 狀態
   - 開發過程中最困難的三個問題與解法

---

現在開始：先偵測環境並寫 `docs/ENVIRONMENT.md`，接著寫 `docs/PLAN.md`，然後進入 M0。
