# KaraForge 合成測資評測(test,產生器 v1)

產生時間:2026-11-21 04:33

- karaforge: 0.1.0.dev0
- python: 3.12.3
- machine: x86_64
- cpu: x86_64
- threads: 8
- device: cpu
- commit: 8f43048
- started: 2026-11-21T04:01:51+08:00
- finished: 2026-11-21T04:33:37+08:00

> 分組 `test`;設定檔 `balanced`;音檔 120 個。

## 與規格 §10.4 目標對照

設定:`balanced`,中文,10 dB(共 747 個 token)

| 指標 | 目標 | 實測 | 結果 |
|---|---:|---:|---|
| 起始時間誤差中位數 (ms) | ≤ 60 | 11.0 | 達成 |
| 起始時間誤差 P95 (ms) | ≤ 250 | 86.0 | 達成 |
| 需人工修正比例(誤差 > 150 ms,%) | ≤ 10 | 2.8 | 達成 |
| 隨機 lock 5% 錨點後的需人工修正比例(%) | ≤ 5 | 3.0 | 達成 |

## 各設定的對齊準確度

### zh,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 20 | 93 | 266 | 7.0% | 0.1% | +17 |
| `balanced / anchors-random-5%` | 711 | 20 | 96 | 272 | 7.2% | 0.1% | +16 |
| `balanced / anchors-lowconf-5%` | 711 | 20 | 86 | 132 | 4.6% | 0.0% | +16 |
| `balanced / anchors-random-5% (v7 handling)` | 711 | 20 | 94 | 241 | 6.9% | 0.1% | +16 |

### zh,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 13 | 66 | 106 | 3.7% | 0.0% | -3 |
| `balanced / anchors-random-5%` | 711 | 13 | 71 | 128 | 4.5% | 0.1% | -4 |
| `balanced / anchors-lowconf-5%` | 711 | 13 | 56 | 86 | 2.3% | 0.0% | -4 |
| `balanced / anchors-random-5% (v7 handling)` | 711 | 14 | 72 | 132 | 4.8% | 0.3% | -3 |

### zh,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 11 | 54 | 86 | 2.8% | 0.0% | -4 |
| `balanced / anchors-random-5%` | 711 | 12 | 56 | 94 | 3.0% | 0.0% | -4 |
| `balanced / anchors-lowconf-5%` | 711 | 11 | 49 | 76 | 1.7% | 0.0% | -4 |
| `balanced / anchors-random-5% (v7 handling)` | 711 | 12 | 65 | 128 | 4.2% | 0.0% | -4 |

### zh,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 8 | 46 | 88 | 3.5% | 0.1% | -4 |
| `balanced / anchors-random-5%` | 711 | 8 | 43 | 70 | 2.7% | 0.1% | -4 |
| `balanced / anchors-lowconf-5%` | 711 | 8 | 40 | 60 | 2.7% | 0.3% | -4 |
| `balanced / anchors-random-5% (v7 handling)` | 711 | 8 | 45 | 78 | 3.1% | 0.1% | -4 |

### en,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 20 | 107 | 139 | 4.3% | 0.6% | -8 |
| `balanced / anchors-random-5%` | 447 | 20 | 105 | 138 | 4.0% | 0.7% | -7 |
| `balanced / anchors-lowconf-5%` | 447 | 19 | 103 | 137 | 3.8% | 0.4% | -8 |
| `balanced / anchors-random-5% (v7 handling)` | 447 | 20 | 136 | 365 | 8.9% | 0.7% | -8 |

### en,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 16 | 103 | 128 | 3.2% | 0.2% | -9 |
| `balanced / anchors-random-5%` | 447 | 16 | 105 | 128 | 3.4% | 0.2% | -9 |
| `balanced / anchors-lowconf-5%` | 447 | 15 | 101 | 124 | 2.9% | 0.0% | -9 |
| `balanced / anchors-random-5% (v7 handling)` | 447 | 17 | 123 | 194 | 7.2% | 0.0% | -9 |

### en,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 14 | 115 | 149 | 5.1% | 0.6% | -9 |
| `balanced / anchors-random-5%` | 447 | 14 | 112 | 138 | 4.3% | 0.7% | -9 |
| `balanced / anchors-lowconf-5%` | 447 | 14 | 105 | 129 | 3.4% | 0.4% | -9 |
| `balanced / anchors-random-5% (v7 handling)` | 447 | 15 | 123 | 174 | 6.9% | 0.4% | -9 |

### en,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 20 | 120 | 164 | 6.6% | 1.7% | -10 |
| `balanced / anchors-random-5%` | 447 | 18 | 114 | 153 | 5.4% | 0.9% | -10 |
| `balanced / anchors-lowconf-5%` | 447 | 15 | 114 | 145 | 4.5% | 0.4% | -10 |
| `balanced / anchors-random-5% (v7 handling)` | 447 | 21 | 130 | 195 | 8.7% | 0.2% | -10 |

### mixed,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 28 | 246 | 515 | 14.1% | 1.7% | -1 |
| `balanced / anchors-random-5%` | 621 | 28 | 231 | 462 | 13.7% | 1.8% | +2 |
| `balanced / anchors-lowconf-5%` | 621 | 26 | 172 | 308 | 11.0% | 0.0% | -1 |
| `balanced / anchors-random-5% (v7 handling)` | 621 | 29 | 311 | 590 | 16.6% | 1.9% | +13 |

### mixed,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 17 | 142 | 334 | 9.8% | 0.2% | -6 |
| `balanced / anchors-random-5%` | 621 | 17 | 128 | 309 | 9.2% | 0.2% | -6 |
| `balanced / anchors-lowconf-5%` | 621 | 17 | 103 | 234 | 7.6% | 0.2% | -7 |
| `balanced / anchors-random-5% (v7 handling)` | 621 | 18 | 153 | 358 | 10.3% | 0.2% | -6 |

### mixed,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 14 | 121 | 302 | 8.7% | 0.5% | -6 |
| `balanced / anchors-random-5%` | 621 | 14 | 120 | 311 | 8.5% | 0.5% | -6 |
| `balanced / anchors-lowconf-5%` | 621 | 13 | 110 | 284 | 7.9% | 0.6% | -6 |
| `balanced / anchors-random-5% (v7 handling)` | 621 | 14 | 115 | 288 | 8.2% | 0.2% | -6 |

### mixed,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 10 | 129 | 651 | 9.3% | 3.1% | -5 |
| `balanced / anchors-random-5%` | 621 | 10 | 100 | 201 | 6.4% | 0.6% | -6 |
| `balanced / anchors-lowconf-5%` | 621 | 10 | 92 | 150 | 5.0% | 0.5% | -6 |
| `balanced / anchors-random-5% (v7 handling)` | 621 | 10 | 111 | 299 | 8.4% | 0.2% | -6 |

## 錨點對其餘 token 的影響(同一批 token,鎖定前 → 鎖定後)

每一列把錨點實驗裡沒有被鎖定的 token,與 `balanced`(沒有錨點)裡的同一個 token 配對;「需修正」指起始時間誤差超過 150 ms。「修好」是鎖定錨點後從需修正變成不需修正的 token 數,「弄壞」是反過來。

| 設定 | 語言 | tokens | 鎖定前需修正 | 鎖定後需修正 | 修好 | 弄壞 |
|---|---|---:|---:|---:|---:|---:|
| `balanced / anchors-random-5%` | zh | 2844 | 4.2% | 4.3% | 4 | 8 |
| `balanced / anchors-random-5%` | en | 1788 | 4.9% | 4.3% | 12 | 1 |
| `balanced / anchors-random-5%` | mixed | 2484 | 10.4% | 9.5% | 26 | 3 |
| `balanced / anchors-random-5%` | all | 7116 | 6.5% | 6.1% | 42 | 12 |
| `balanced / anchors-lowconf-5%` | zh | 2844 | 2.5% | 2.8% | 2 | 12 |
| `balanced / anchors-lowconf-5%` | en | 1788 | 4.3% | 3.6% | 12 | 0 |
| `balanced / anchors-lowconf-5%` | mixed | 2484 | 9.0% | 7.9% | 34 | 6 |
| `balanced / anchors-lowconf-5%` | all | 7116 | 5.2% | 4.8% | 48 | 18 |
| `balanced / anchors-random-5% (v7 handling)` | zh | 2844 | 4.2% | 4.7% | 12 | 28 |
| `balanced / anchors-random-5% (v7 handling)` | en | 1788 | 4.9% | 7.9% | 18 | 73 |
| `balanced / anchors-random-5% (v7 handling)` | mixed | 2484 | 10.4% | 10.9% | 46 | 58 |
| `balanced / anchors-random-5% (v7 handling)` | all | 7116 | 6.5% | 7.7% | 76 | 159 |

## 結束時間(行尾長音)與信心度

| 設定 | 語言 | SNR | 行尾結束誤差中位數 ms | 行尾結束誤差 P90 ms | 信心度 AUROC | 檢查信心最低 10% 找到的問題比例 | 20% |
|---|---|---:|---:|---:|---:|---:|---:|
| `balanced` | zh | 0 dB | 76 | 551 | 0.89 | 58% | 77% |
| `balanced / anchors-random-5%` | zh | 0 dB | 76 | 530 | 0.89 | 65% | 76% |
| `balanced / anchors-lowconf-5%` | zh | 0 dB | 58 | 425 | 0.89 | 61% | 82% |
| `balanced / anchors-random-5% (v7 handling)` | zh | 0 dB | 76 | 530 | 0.89 | 57% | 73% |
| `balanced` | zh | 5 dB | 26 | 332 | 0.93 | 71% | 89% |
| `balanced / anchors-random-5%` | zh | 5 dB | 27 | 545 | 0.95 | 78% | 94% |
| `balanced / anchors-lowconf-5%` | zh | 5 dB | 24 | 244 | 0.92 | 69% | 88% |
| `balanced / anchors-random-5% (v7 handling)` | zh | 5 dB | 27 | 545 | 0.93 | 68% | 91% |
| `balanced` | zh | 10 dB | 18 | 176 | 0.93 | 67% | 90% |
| `balanced / anchors-random-5%` | zh | 10 dB | 19 | 169 | 0.93 | 67% | 86% |
| `balanced / anchors-lowconf-5%` | zh | 10 dB | 18 | 172 | 0.93 | 75% | 92% |
| `balanced / anchors-random-5% (v7 handling)` | zh | 10 dB | 19 | 169 | 0.93 | 63% | 87% |
| `balanced` | zh | 20 dB | 7 | 121 | 0.91 | 73% | 77% |
| `balanced / anchors-random-5%` | zh | 20 dB | 7 | 130 | 0.91 | 74% | 74% |
| `balanced / anchors-lowconf-5%` | zh | 20 dB | 7 | 133 | 0.90 | 68% | 74% |
| `balanced / anchors-random-5% (v7 handling)` | zh | 20 dB | 7 | 136 | 0.92 | 73% | 77% |
| `balanced` | en | 0 dB | 273 | 841 | 0.76 | 50% | 60% |
| `balanced / anchors-random-5%` | en | 0 dB | 278 | 871 | 0.77 | 56% | 67% |
| `balanced / anchors-lowconf-5%` | en | 0 dB | 256 | 840 | 0.75 | 47% | 53% |
| `balanced / anchors-random-5% (v7 handling)` | en | 0 dB | 288 | 1158 | 0.84 | 48% | 78% |
| `balanced` | en | 5 dB | 56 | 798 | 0.75 | 60% | 67% |
| `balanced / anchors-random-5%` | en | 5 dB | 49 | 817 | 0.75 | 60% | 67% |
| `balanced / anchors-lowconf-5%` | en | 5 dB | 54 | 683 | 0.70 | 54% | 54% |
| `balanced / anchors-random-5% (v7 handling)` | en | 5 dB | 103 | 821 | 0.83 | 56% | 72% |
| `balanced` | en | 10 dB | 26 | 796 | 0.76 | 58% | 62% |
| `balanced / anchors-random-5%` | en | 10 dB | 26 | 800 | 0.76 | 53% | 63% |
| `balanced / anchors-lowconf-5%` | en | 10 dB | 24 | 619 | 0.69 | 40% | 53% |
| `balanced / anchors-random-5% (v7 handling)` | en | 10 dB | 30 | 829 | 0.83 | 58% | 65% |
| `balanced` | en | 20 dB | 12 | 448 | 0.76 | 55% | 71% |
| `balanced / anchors-random-5%` | en | 20 dB | 12 | 444 | 0.71 | 58% | 62% |
| `balanced / anchors-lowconf-5%` | en | 20 dB | 11 | 208 | 0.65 | 50% | 50% |
| `balanced / anchors-random-5% (v7 handling)` | en | 20 dB | 11 | 237 | 0.78 | 56% | 69% |
| `balanced` | mixed | 0 dB | 113 | 1372 | 0.82 | 35% | 54% |
| `balanced / anchors-random-5%` | mixed | 0 dB | 104 | 1388 | 0.83 | 35% | 56% |
| `balanced / anchors-lowconf-5%` | mixed | 0 dB | 104 | 1360 | 0.81 | 31% | 53% |
| `balanced / anchors-random-5% (v7 handling)` | mixed | 0 dB | 122 | 1480 | 0.85 | 38% | 59% |
| `balanced` | mixed | 5 dB | 23 | 1233 | 0.85 | 42% | 69% |
| `balanced / anchors-random-5%` | mixed | 5 dB | 22 | 1224 | 0.85 | 42% | 67% |
| `balanced / anchors-lowconf-5%` | mixed | 5 dB | 24 | 1230 | 0.84 | 45% | 62% |
| `balanced / anchors-random-5% (v7 handling)` | mixed | 5 dB | 22 | 1306 | 0.87 | 44% | 73% |
| `balanced` | mixed | 10 dB | 13 | 900 | 0.81 | 47% | 60% |
| `balanced / anchors-random-5%` | mixed | 10 dB | 14 | 926 | 0.81 | 49% | 58% |
| `balanced / anchors-lowconf-5%` | mixed | 10 dB | 14 | 876 | 0.83 | 55% | 65% |
| `balanced / anchors-random-5% (v7 handling)` | mixed | 10 dB | 14 | 741 | 0.79 | 43% | 59% |
| `balanced` | mixed | 20 dB | 10 | 103 | 0.86 | 52% | 74% |
| `balanced / anchors-random-5%` | mixed | 20 dB | 10 | 40 | 0.78 | 38% | 60% |
| `balanced / anchors-lowconf-5%` | mixed | 20 dB | 10 | 40 | 0.82 | 55% | 68% |
| `balanced / anchors-random-5% (v7 handling)` | mixed | 20 dB | 10 | 44 | 0.81 | 46% | 65% |

## 處理時間(每分鐘音訊所需秒數,CPU)

| 設定 | ingest | separate | analyze | asr | align | 合計 | 即時倍率 |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 2.3 | 29.3 | 0.4 | 12.4 | 13.4 | 57.9 | 1.0x |
| `balanced / anchors-random-5%` | 2.3 | 29.3 | 0.4 | 12.4 | 0.2 | 44.6 | 1.3x |
| `balanced / anchors-lowconf-5%` | 2.3 | 29.3 | 0.4 | 12.4 | 0.2 | 44.6 | 1.3x |
| `balanced / anchors-random-5% (v7 handling)` | 2.3 | 29.3 | 0.4 | 12.4 | 0.2 | 44.6 | 1.3x |

時間是各階段「實際計算」時記錄下來的秒數;同一首歌的後續設定會沿用分離與辨識的快取,但表中仍列出該階段原本的計算時間。

