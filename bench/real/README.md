# 真實歌曲評測（資料不進版控）

合成測資和真的歌有差距。如果你手上有可以合法使用的歌，並且願意花時間把逐字時間校正到正確，
就可以用這個套件量測 KaraForge 在真實歌曲上的表現。**歌曲與校正檔都不會被提交**（`bench/real/songs/` 已被 git 忽略）。

## 資料夾結構

```
bench/real/songs/
├── my-song-1/
│   ├── song.flac          # 任何 KaraForge 能讀的媒體檔，一個資料夾一首
│   └── project.json       # 人工校正過的專案檔（標準答案）
└── my-song-2/
    ├── clip.mp4
    └── project.json
```

## 怎麼做標準答案

1. `kf new song.flac --lyrics lyrics.txt -o work.kfproj`，然後 `kf run work.kfproj`。
2. `kf serve`，在編輯器裡把**每一個字**的開始與結束時間修到你認為正確為止。
   建議用 0.5x 速度搭配「只聽人聲」，並用打點模式重新敲一次再微調。
3. 把 `work.kfproj/project.json` 複製到這首歌的資料夾。

評測只會用到 `project.json` 裡每一行的文字、演唱者與 token 的 `start_ms`／`end_ms`；
每一行的每個 token 都必須有時間。

## 執行

```bash
kf bench --suite real                      # 預設設定檔 balanced
kf bench --suite real --aligner ctc --aligner whisper-attn --ablation
```

報告寫到 `bench/_runs/reports/real-test-<profile>/`。指標的定義與合成測資相同（見 `docs/benchmark.md`）；
標準答案的品質取決於你的校正，所以誤差的下限大約就是人工標記本身的誤差（通常 20–50 ms）。
