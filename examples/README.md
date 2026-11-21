# 範例

`demo/` 是用 KaraForge 自己的合成測資做出來的一個完整例子：從一首歌加歌詞，到 KTV 影片。
裡面沒有任何有著作權的素材——歌聲是語音合成後改成旋律，伴奏是程式合成的，歌詞是為這個專案寫的。

| 檔案 | 內容 |
|---|---|
| `demo/song.mp3` | 輸入：48.5 秒的合成歌曲（人聲比伴奏大 10 dB），與 `tests/fixtures/songs/zh-2000/mix_snr10.mp3` 相同 |
| `demo/lyrics.txt` | 輸入：歌詞（四行、兩段） |
| `demo/demo-ktv.mp4` | 輸出：字幕燒進畫面的影片，1280×720，伴奏音軌，`classic-ktv` 主題 |
| `demo/demo-ktv.mkv` | 輸出：軟字幕（ASS）+ 伴唱與原唱兩條音軌 + 內嵌字型，`pop-round` 主題 |
| `demo/demo.enhanced.lrc` | 輸出：逐字的 enhanced LRC |
| `demo/project.json` | 處理後的專案檔（對齊結果、自動讀音、分析結果）；格式見 [docs/project-format.md](../docs/project-format.md) |

## 這些檔案是怎麼產生的

全部是自動結果，**沒有手動修過任何一個字**。在 `demo/` 資料夾裡執行（2026-11-21，`balanced` 設定檔，CPU）：

```bash
kf auto song.mp3 lyrics.txt -o demo-ktv.mp4 --res 720p
kf export demo-ktv.kfproj --format elrc -o demo.enhanced.lrc
# MKV 用另一個主題：把 demo-ktv.kfproj/project.json 的 style.theme 改成 "pop-round" 之後
kf export demo-ktv.kfproj --format mkv --res 720p -o demo-ktv.mkv
```

`kf auto` 那一步花了 57 秒（分離人聲 26 秒、語音辨識 7 秒、對齊 11 秒、輸出影片 7 秒；
機器是 Intel i5-10500，沒有 GPU，當時同時還在建置 Docker 映像）。專案資料夾 `demo-ktv.kfproj/` 含有分離出來的音軌與快取，
沒有放進版控；這裡只附上它的 `project.json`。

MKV 用 `pop-round` 而不是預設主題，是因為軟字幕要把字型嵌進檔案：預設主題的字型有 15.8 MB，換成 4.9 MB 的字型後檔案從 19 MB 降到 8 MB。

## 這個例子有多準

這首歌有標準答案（`tests/fixtures/songs/zh-2000/truth.json`），所以可以直接量：
43 個字的開始時間，誤差中位數 12 毫秒、最大 114 毫秒，沒有任何一個字超過 150 毫秒。

```bash
python scripts/compare_with_truth.py examples/demo/project.json tests/fixtures/songs/zh-2000/truth.json
```

**這是一個容易的例子**，請不要當成一般情況：合成的歌聲咬字清楚、伴奏單純、人聲比伴奏大聲。
整體的評測數字（包含比較差的情況）在 [docs/benchmark.md](../docs/benchmark.md)。

## 自己試試看

```bash
cd examples/demo
kf auto song.mp3 lyrics.txt -o my-ktv.mp4            # 重現上面的結果
kf auto song.mp3 -o draft-ktv.mp4                     # 不給歌詞：語音辨識草稿（會錯很多，見 docs/lyrics-format.md）
kf serve --workspace . --open                         # 在編輯器裡打開剛剛產生的專案
```

在編輯器的主題面板把「顯示注音／拼音」打開，就會看到每個字上方的讀音。
