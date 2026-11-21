# 撰寫 adapter：接上新的模型

KaraForge 的引擎不直接呼叫任何模型函式庫；分離、語音辨識、強制對齊各是一個 Protocol（`engine/karaforge/adapters/base.py`），
模型藏在實作後面。要換一個模型，就是寫一個類別、在註冊表加一行、（需要的話）在模型註冊表登記權重。

這份指南以最常見的情況——**新的強制對齊器**——為例；分離器與語音辨識器的步驟相同。

## 三個 Protocol

```python
class Separator(Protocol):
    @property
    def info(self) -> AdapterInfo: ...
    def separate(self, audio: Path, out_dir: Path, *, progress, cancel) -> SeparationResult:
        ...
        # 讀一個 WAV，在 out_dir 寫出 vocals.wav 與 instrumental.wav


class Transcriber(Protocol):
    @property
    def info(self) -> AdapterInfo: ...
    def transcribe(self, audio, *, language, prompt, progress, cancel) -> Transcript:
        ...
        # audio：16 kHz 單聲道 float32；回傳帶逐詞時間的 Transcript


class Aligner(Protocol):
    @property
    def info(self) -> AdapterInfo: ...
    def align(self, request: AlignRequest) -> list[UnitTiming]:
        ...
        # 把 request.units（一行歌詞的字）放到 request.audio（那一行的時間窗）上
```

共同的約定：

- **音訊**：給模型的一律是 16 kHz、單聲道、float32、範圍 −1 到 1 的 NumPy 陣列（分離器例外：它讀檔案，取樣率自理）。
- **時間**：秒（float），相對於傳進來的那段音訊的開頭。
- **進度與取消**：長時間的工作要定期呼叫 `progress(0–1, "中文 / English")`，並在適當的地方呼叫 `cancel.raise_if_cancelled()`。
- **錯誤**：丟出 `karaforge.errors` 裡的例外（附中英文訊息與建議），不要讓函式庫的例外直接冒出去。
- **延遲匯入**：`import torch` 之類的要寫在方法裡，不要寫在模組頂端。模型在第一次需要時才載入，並且透過
  `adapters/pool.py` 的 `shared(key, factory)` 共用——同一個模型在一個行程裡只會載入一次
  （例如語音辨識與 `whisper-attn` 對齊器共用同一個 Whisper）。目前沒有自動釋放的機制：載入後會留在記憶體裡直到行程結束。

## `AdapterInfo`：自我描述

```python
AdapterInfo(
    name="my-aligner",
    version="1",  # 輸出會改變時就要加一：它是快取鍵的一部分
    license="Apache-2.0",  # 「權重」的授權
    languages=("zh", "en"),  # BCP-47 的語言前綴；("*",) 表示不限語言
    devices=("cpu", "cuda"),
    memory_mb=1500,  # 大約的尖峰記憶體用量
    description_zh="…",
    description_en="…",
    models=("my-model-id",),  # 需要的模型（模型註冊表裡的 id）
)
```

`version` 很重要：對齊結果是照「輸入的內容 + adapter 的名稱@版本 + 參數」快取的。改了會影響輸出的程式而沒有改版本，
使用者會繼續拿到舊的快取結果。

## 對齊器的細節

`AlignRequest` 給你：

| 欄位 | 說明 |
|---|---|
| `audio` | 這一行的時間窗（前後各多留了一點） |
| `units` | 要對齊的字：`text`（不含標點的核心文字）、`kind`（漢字、假名、拉丁詞…）、`reading`（已知的羅馬拼音，中文是不帶聲調的拼音） |
| `language` | 專案語言 |
| `open_start`／`open_end` | 時間窗的開頭／結尾可能有**不屬於這一行**的聲音（鄰行的尾巴或開頭） |
| `prefix_units`／`suffix_units` | 那些可能聽得到的鄰行的字；可以用來「吸收」那段聲音，但不要回傳它們的時間 |
| `offset_s` | 這段音訊在整首人聲軌裡的起點（給有 `prepare` 的對齊器用） |

回傳 `list[UnitTiming]`：**每個 unit 一筆、順序相同、開始時間不遞減**；`score` 是你對這個位置的把握（0–1）。
`score` 會成為信心度的一部分，也用來判斷「這個字其實沒有證據」，所以請讓它有意義——全部回傳 1.0 會讓下游的補救機制失效。

選用的屬性（對齊流程用 `getattr` 找）：

| 屬性 | 用途 |
|---|---|
| `prepare(audio)` | 開始逐行對齊之前，先拿到整首人聲軌一次。聲學模型與文字無關的對齊器（CTC）可以在這裡把整首跑完，之後每一行、每一次重新對齊都只是查表。 |
| `max_window_s` | 能接受的最長時間窗。一行的時間窗超過時，流程會以它的中心為準縮到這個長度。 |
| `lead_ms` | 這個對齊器的系統性偏差（例如 CTC 模型通常在音節開始後一點才「亮」）；會從每個開始時間扣掉。**請用開發資料校正，不要用測試資料。** |
| `weak_score` | 分數低於這個值的字視為「沒有證據」，精修階段會試著把它放到附近沒被佔用的起音點。 |

你**不需要**處理：把整首歌切成行（粗對齊做）、吸附起音點、字的結束時間、長音、排序、信心度、鎖定的錨點——這些都在
`engine/karaforge/align/` 裡，對所有對齊器一視同仁。對齊器只回答一個問題：「這一小段聲音裡，這幾個字各在哪裡？」

## 接上去

1. **寫類別**：放在 `engine/karaforge/adapters/aligners/my_aligner.py`。現有的 `whisper_attention.py`（不到 200 行）是最短的完整範例。
2. **註冊**：在 `adapters/registry.py` 的 `ALIGNERS` 加上名字，並在 `create_aligner` 加一個分支（在分支裡才 `import`）。
3. **登記權重**（如果要自動下載）：在 `scripts/update_model_registry.py` 的 `SOURCES` 加上來源（Hugging Face 的 repo 與要哪些檔案，或直接的網址），
   執行它會釘住上游當下的 commit，並把每個檔案的大小與 SHA-256 寫進 `engine/karaforge/models/registry.json`。
   授權不允許商業使用的，把 `commercial_use` 設為 `false`——使用者必須明確同意才會下載。
4. **測試**：
   - 不需要權重的單元測試：把模型換成假的輸出，測你的前處理與後處理（見 `tests/unit/test_ctc_adapter.py`、`test_qwen_adapter.py`）。
   - 需要權重的測試加上 `@pytest.mark.models`，沒有權重時會自動跳過。
5. **量測**：

   ```bash
   # 只用開發分組調整與校正
   python -m kfbench.tune --aligner my-aligner --grid align.lead_ms=-60,-30,0,30
   # 定案之後才跑測試分組，並與現有的對齊器並列
   kf bench --split test --aligner my-aligner
   ```

   評測的規矩（不在測試分組上調參數、不改測試資料）寫在 [benchmark.md](benchmark.md)。
6. **授權**：在 [LICENSES.md](LICENSES.md) 加上權重與新相依套件的授權。相依套件很重或有版本衝突的，做成選用的 extra
   （`qwen` 就是這樣處理的，見 `pyproject.toml`）。

## 使用新的 adapter

```bash
kf run my-song.kfproj --set align.aligner=my-aligner
```

想讓它成為某個設定檔的預設值，改 `engine/karaforge/pipeline/profiles.py`——並附上評測結果說明為什麼。
