# KaraForge 合成測資評測(dev,產生器 v1)

產生時間:2026-11-21 03:59

- karaforge: 0.1.0.dev0
- python: 3.12.3
- machine: x86_64
- cpu: x86_64
- threads: 8
- device: cpu
- commit: 3dd0d6a-dirty
- started: 2026-11-21T03:49:02+08:00
- finished: 2026-11-21T03:59:30+08:00

> 分組 `dev`;設定檔 `balanced`;音檔 48 個。

## 與規格 §10.4 目標對照

設定:`balanced`,中文,10 dB(共 272 個 token)

| 指標 | 目標 | 實測 | 結果 |
|---|---:|---:|---|
| 起始時間誤差中位數 (ms) | ≤ 60 | 11.0 | 達成 |
| 起始時間誤差 P95 (ms) | ≤ 250 | 90.9 | 達成 |
| 需人工修正比例(誤差 > 150 ms,%) | ≤ 10 | 2.9 | 達成 |
| 隨機 lock 5% 錨點後的需人工修正比例(%) | ≤ 5 | 2.7 | 達成 |

## 各設定的對齊準確度

### zh,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 18 | 99 | 260 | 6.2% | 0.0% | +10 |
| `balanced / anchors-random-5%` | 259 | 18 | 106 | 324 | 8.1% | 0.8% | +12 |
| `balanced / anchors-lowconf-5%` | 259 | 18 | 99 | 258 | 6.9% | 0.4% | +12 |

### zh,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 13 | 65 | 96 | 3.7% | 0.0% | -3 |
| `balanced / anchors-random-5%` | 259 | 12 | 61 | 92 | 2.3% | 0.0% | -3 |
| `balanced / anchors-lowconf-5%` | 259 | 12 | 59 | 80 | 1.5% | 0.0% | -3 |

### zh,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 11 | 55 | 91 | 2.9% | 0.0% | -4 |
| `balanced / anchors-random-5%` | 259 | 11 | 54 | 86 | 2.7% | 0.0% | -4 |
| `balanced / anchors-lowconf-5%` | 259 | 11 | 53 | 83 | 2.3% | 0.0% | -4 |

### zh,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 8 | 44 | 65 | 2.6% | 0.0% | -2 |
| `balanced / anchors-random-5%` | 259 | 8 | 44 | 74 | 2.7% | 0.0% | -2 |
| `balanced / anchors-lowconf-5%` | 259 | 7 | 40 | 49 | 0.8% | 0.0% | -3 |

### en,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 42 | 151 | 203 | 10.3% | 0.0% | +26 |
| `balanced / anchors-random-5%` | 194 | 42 | 160 | 206 | 10.3% | 0.0% | +26 |
| `balanced / anchors-lowconf-5%` | 194 | 40 | 118 | 198 | 8.2% | 0.0% | +24 |

### en,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 26 | 120 | 172 | 5.9% | 0.0% | -6 |
| `balanced / anchors-random-5%` | 194 | 28 | 122 | 183 | 6.2% | 0.0% | -6 |
| `balanced / anchors-lowconf-5%` | 194 | 24 | 109 | 135 | 4.1% | 0.0% | -6 |

### en,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 17 | 130 | 290 | 8.3% | 2.0% | -7 |
| `balanced / anchors-random-5%` | 194 | 15 | 114 | 146 | 4.6% | 0.0% | -7 |
| `balanced / anchors-lowconf-5%` | 194 | 14 | 100 | 122 | 3.1% | 0.0% | -7 |

### en,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 17 | 145 | 345 | 9.8% | 2.5% | -6 |
| `balanced / anchors-random-5%` | 194 | 13 | 114 | 166 | 5.7% | 0.0% | -6 |
| `balanced / anchors-lowconf-5%` | 194 | 13 | 111 | 143 | 4.6% | 0.0% | -6 |

### mixed,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 38 | 311 | 582 | 13.9% | 0.5% | -4 |
| `balanced / anchors-random-5%` | 177 | 33 | 205 | 488 | 10.7% | 0.6% | -3 |
| `balanced / anchors-lowconf-5%` | 177 | 38 | 318 | 595 | 13.6% | 0.6% | -5 |

### mixed,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 19 | 286 | 748 | 13.9% | 0.5% | -8 |
| `balanced / anchors-random-5%` | 177 | 16 | 212 | 540 | 11.3% | 0.6% | -7 |
| `balanced / anchors-lowconf-5%` | 177 | 16 | 169 | 468 | 10.7% | 0.0% | -8 |

### mixed,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 14 | 288 | 754 | 15.0% | 0.5% | -8 |
| `balanced / anchors-random-5%` | 177 | 13 | 251 | 720 | 14.1% | 0.0% | -8 |
| `balanced / anchors-lowconf-5%` | 177 | 12 | 173 | 673 | 10.7% | 0.0% | -8 |

### mixed,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 10 | 221 | 460 | 11.8% | 0.5% | -7 |
| `balanced / anchors-random-5%` | 177 | 10 | 212 | 377 | 11.3% | 0.6% | -7 |
| `balanced / anchors-lowconf-5%` | 177 | 10 | 117 | 338 | 9.0% | 0.6% | -7 |

## 結束時間(行尾長音)與信心度

| 設定 | 語言 | SNR | 行尾結束誤差中位數 ms | 行尾結束誤差 P90 ms | 信心度 AUROC | 檢查信心最低 10% 找到的問題比例 | 20% |
|---|---|---:|---:|---:|---:|---:|---:|
| `balanced` | zh | 0 dB | 68 | 393 | 0.88 | 59% | 71% |
| `balanced / anchors-random-5%` | zh | 0 dB | 68 | 393 | 0.85 | 57% | 67% |
| `balanced / anchors-lowconf-5%` | zh | 0 dB | 70 | 424 | 0.88 | 44% | 67% |
| `balanced` | zh | 5 dB | 21 | 146 | 0.95 | 70% | 90% |
| `balanced / anchors-random-5%` | zh | 5 dB | 21 | 146 | 0.98 | 100% | 100% |
| `balanced / anchors-lowconf-5%` | zh | 5 dB | 21 | 178 | 0.99 | 100% | 100% |
| `balanced` | zh | 10 dB | 14 | 132 | 0.95 | 75% | 88% |
| `balanced / anchors-random-5%` | zh | 10 dB | 14 | 82 | 0.94 | 71% | 100% |
| `balanced / anchors-lowconf-5%` | zh | 10 dB | 14 | 82 | 0.97 | 83% | 100% |
| `balanced` | zh | 20 dB | 10 | 22 | 0.99 | 100% | 100% |
| `balanced / anchors-random-5%` | zh | 20 dB | 9 | 23 | 0.99 | 100% | 100% |
| `balanced / anchors-lowconf-5%` | zh | 20 dB | 9 | 18 | 0.99 | 100% | 100% |
| `balanced` | en | 0 dB | 599 | 1444 | 0.84 | 43% | 67% |
| `balanced / anchors-random-5%` | en | 0 dB | 599 | 1462 | 0.86 | 45% | 70% |
| `balanced / anchors-lowconf-5%` | en | 0 dB | 599 | 1453 | 0.81 | 38% | 75% |
| `balanced` | en | 5 dB | 112 | 579 | 0.92 | 58% | 100% |
| `balanced / anchors-random-5%` | en | 5 dB | 112 | 579 | 0.92 | 58% | 92% |
| `balanced / anchors-lowconf-5%` | en | 5 dB | 112 | 579 | 0.92 | 38% | 100% |
| `balanced` | en | 10 dB | 30 | 384 | 0.96 | 71% | 94% |
| `balanced / anchors-random-5%` | en | 10 dB | 17 | 375 | 0.96 | 89% | 89% |
| `balanced / anchors-lowconf-5%` | en | 10 dB | 16 | 375 | 0.96 | 83% | 100% |
| `balanced` | en | 20 dB | 22 | 235 | 0.96 | 60% | 95% |
| `balanced / anchors-random-5%` | en | 20 dB | 19 | 229 | 0.95 | 73% | 91% |
| `balanced / anchors-lowconf-5%` | en | 20 dB | 21 | 228 | 0.96 | 78% | 100% |
| `balanced` | mixed | 0 dB | 454 | 2129 | 0.75 | 23% | 42% |
| `balanced / anchors-random-5%` | mixed | 0 dB | 590 | 2037 | 0.76 | 26% | 42% |
| `balanced / anchors-lowconf-5%` | mixed | 0 dB | 454 | 2129 | 0.76 | 25% | 46% |
| `balanced` | mixed | 5 dB | 88 | 2102 | 0.79 | 35% | 50% |
| `balanced / anchors-random-5%` | mixed | 5 dB | 75 | 2060 | 0.82 | 45% | 60% |
| `balanced / anchors-lowconf-5%` | mixed | 5 dB | 75 | 2060 | 0.80 | 37% | 47% |
| `balanced` | mixed | 10 dB | 26 | 2100 | 0.79 | 36% | 50% |
| `balanced / anchors-random-5%` | mixed | 10 dB | 26 | 2100 | 0.80 | 36% | 48% |
| `balanced / anchors-lowconf-5%` | mixed | 10 dB | 26 | 2093 | 0.78 | 26% | 47% |
| `balanced` | mixed | 20 dB | 12 | 1186 | 0.79 | 36% | 64% |
| `balanced / anchors-random-5%` | mixed | 20 dB | 12 | 1180 | 0.77 | 40% | 60% |
| `balanced / anchors-lowconf-5%` | mixed | 20 dB | 11 | 1180 | 0.77 | 31% | 56% |

## 處理時間(每分鐘音訊所需秒數,CPU)

| 設定 | ingest | separate | analyze | asr | align | 合計 | 即時倍率 |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 2.0 | 37.6 | 0.5 | 18.2 | 11.2 | 69.5 | 0.9x |
| `balanced / anchors-random-5%` | 2.0 | 37.6 | 0.5 | 18.2 | 0.1 | 58.4 | 1.0x |
| `balanced / anchors-lowconf-5%` | 2.0 | 37.6 | 0.5 | 18.2 | 0.1 | 58.4 | 1.0x |

時間是各階段「實際計算」時記錄下來的秒數;同一首歌的後續設定會沿用分離與辨識的快取,但表中仍列出該階段原本的計算時間。

