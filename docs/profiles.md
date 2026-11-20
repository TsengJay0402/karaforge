# 處理品質設定檔與可調參數

「設定檔」（profile）是一組處理參數：用哪個分離模型、哪個語音辨識模型、哪個對齊器，以及對齊演算法的各個旋鈕。
用 `--profile` 選（CLI），或在 Web 的新增精靈裡選「快速／平衡／高品質」。

## 三個內建設定檔

| | `cpu-lite`（快速） | `balanced`（平衡，預設） | `gpu-quality`（高品質） |
|---|---|---|---|
| 人聲分離 | UVR MDX-Net Kara 2 | 同左 | 同左 |
| 語音辨識 | Whisper base（beam 2） | Whisper small（beam 5） | Whisper large-v3-turbo（beam 5） |
| 對齊器 | `whisper-attn`：沿用語音辨識的 Whisper 模型 | `ctc`：wav2vec2 中文 + 英文 | `auto`：裝了 `qwen-asr` 就是 `hybrid`（CTC + Qwen3），否則 `ctc` |
| 需要下載 | 約 0.2 GB | 約 2.2 GB | 約 3.3 GB；加上 Qwen 約 5.2 GB |
| 模型授權 | 全部允許商用 | 全部允許商用 | 全部允許商用 |
| 適合 | 先試試看、CI、記憶體很小的機器 | 一般使用；CPU 就能跑 | 有 GPU，或願意多等 |

怎麼選：

- **沒有特別的理由就用 `balanced`。** 它在我們的評測上對中文最準，而且所有模型都是寬鬆授權。
- `cpu-lite` 的對齊明顯比較不準（見評測報告裡 `balanced+whisper-attn` 那一列——它用的是 Whisper small，`cpu-lite` 實際用的 base 只會更差），
  但下載量只有十分之一。拿來確認流程、或之後打算手動打點時很合適。
- `gpu-quality` 的差別主要在語音辨識（對「沒有歌詞」的流程與歌詞對不上的歌比較有幫助）與英文、中英混合歌詞的對齊（`hybrid`）。
  名字裡有 GPU 是因為 large-v3-turbo 在 CPU 上很慢，不是因為它不能在 CPU 上跑。
- **GPU（CUDA）與 Apple MPS 的路徑沒有在開發環境實測過**（開發機沒有 GPU）；程式會自動偵測並在失敗時退回 CPU，但速度與正確性我們沒有數據。

各對齊器的實測比較在 [benchmark-report.md](benchmark-report.md)，選擇的理由在 [ADR 0006](adr/0006-aligner-choice.md)。

## 覆寫單一參數

```bash
kf run my-song.kfproj --set align.aligner=whisper-attn --set asr.model=whisper-medium
```

格式是 `區段.名稱=值`，可重複。Web API 的工作也接受同樣的 `settings`。寫錯名稱或數值會直接報錯，不會被忽略。

### `device`

`auto`（預設：CUDA → MPS → CPU）、`cpu`、`cuda`、`mps`。也可以用環境變數 `KARAFORGE_DEVICE`。

### `separate.*`

| 參數 | 預設 | 說明 |
|---|---|---|
| `separate.adapter` | `audio-separator` | 分離器 |
| `separate.model` | `uvr-mdxnet-kara-2` | 伴唱型模型：和聲留在伴奏裡（比較接近真正的 KTV 伴唱帶），人聲軌是乾淨的主唱，供對齊使用 |

### `analyze.*`

| 參數 | 預設 | 說明 |
|---|---|---|
| `analyze.vad_min_region_ms` | 200 | 比這短的人聲區段不算 |
| `analyze.vad_merge_gap_ms` | 300 | 間隔在這以內的人聲區段視為同一段 |

### `asr.*`

| 參數 | 預設 | 說明 |
|---|---|---|
| `asr.adapter` | `faster-whisper` | 語音辨識器 |
| `asr.model` | `whisper-small` | `whisper-tiny`／`base`／`small`／`medium`／`large-v3-turbo` |
| `asr.beam_size` | 5 | 越大越準、越慢 |
| `asr.use_lyrics_prompt` | `true` | 用已知的歌詞提示辨識器（語音辨識草稿的專案不會用） |

### `align.*`

| 參數 | 預設 | 說明 |
|---|---|---|
| `align.aligner` | `ctc` | `ctc`、`whisper-attn`、`qwen`、`hybrid`、`auto`、`ctc-mms`（非商業授權） |
| `align.model` | `default` | 對齊器使用的模型 |
| `align.coarse` | `asr` | 行的時間窗怎麼來：`asr`（與語音辨識比對，正常模式）、`regions`（不用辨識結果）、`global`（整首一次對齊）。後兩種是給消融實驗用的。 |
| `align.window_pad_ms` | 1000 | 細對齊時，每一行的時間窗前後各多留多少 |
| `align.context_tokens` | 4 | 鄰行的字可能落在時間窗裡時，給對齊器幾個鄰行的字當上下文 |
| `align.anchor_context` | `true` | 重新對齊時怎麼使用鎖定的字：連同鎖定字一起對齊相鄰的字，行的時間窗同時參考鎖定字與辨識結果。`false` 是舊版（第 7 版）的行為，只供比較 |
| `align.lead_ms` | 依對齊器 | 從每個開始時間扣掉的固定值（對齊器的系統性偏差）；預設用各對齊器在開發資料上校正出來的值 |
| `align.onset_snap` | `true` | 把字的開頭吸附到附近的起音點 |
| `align.onset_snap_ms` | 60 | 最多移動多遠 |
| `align.weak_score` | 依對齊器 | 對齊器分數低於此值的字視為「沒有證據」，改放到鄰字之間最強的、還沒被用掉的起音點；0＝停用 |
| `align.min_token_ms` | 60 | 一個字最短多久 |
| `align.pause_threshold_ms` | 300 | 字與下一個字的間隔超過這個值時，在人聲能量下降處結束這個字 |
| `align.long_note` | `true` | 行尾的字延長到人聲消失為止（長音） |
| `align.max_tail_ms` | 6000 | 行尾延長的上限 |

每個參數在演算法裡的作用見 [alignment.md](alignment.md)。

## 效能

每分鐘音訊需要多少處理時間，評測報告的「處理時間」一節有各階段的實測值（CPU）。要注意那些數字是在一台**同時還在跑其他工作**的機器上量的，
而且推論被限制在 8 個執行緒；它們適合用來看各階段的相對比例，不適合當成你的機器上的預期值。

幾個實用的事實：

- 最慢的是人聲分離與語音辨識；兩者的結果都會被快取，所以**調整對齊參數或修改歌詞後重跑很快**。
- `ctc` 對齊器把整首歌的聲學模型輸出算一次就留在記憶體裡；在同一個行程裡（例如開著的 Web 伺服器）之後每一次重新對齊都不必再跑模型。用 CLI 時每次執行是新的行程，會重算一次。
- `KARAFORGE_THREADS` 可以調整推論用的 CPU 執行緒數。
