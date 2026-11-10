# セキュアカメラ貸出管理システム

> **職場実践実習の課題として作成したものです。** 実際の業務では運用していません。
> 要件の検討から設計・実装・テストまで、AI(Claude)と一緒に考えながら作りました。
> 社名・ブランドカラーは課題の設定上のもので、企業の公式なソフトウェアではありません。

社員証(ICカード)で本人確認をして、セキュアカメラの貸出・返却を記録し、
保管庫の電磁ロックを解錠するシステムです。

- 画面: CustomTkinter(タッチモニター向け)
- 記録: SQLite
- カードリーダー: Sony RC-S380(nfcpy)
- 電磁ロック: gpiozero でリレーを制御
- **デモモード**: カードリーダー・電磁ロックなしで、Windows PC で全体の流れを確認できます

設計の詳細(要件整理・仮定・改善提案・DB設計・リスク・対応表)は
[docs/DESIGN.md](docs/DESIGN.md) を参照してください。

---

## 確認状況(必ず読んでください)

| 項目 | 状況 |
|---|---|
| DB・貸出/返却ロジック(自動テスト78件) | **PC確認済み**(Linux / Python 3.13.18・3.12.3) |
| GUI の画面遷移(貸出〜返却、エラー、解錠失敗、無操作タイムアウト) | **PC確認済み**(Linux + 仮想ディスプレイ / Python 3.12.3 / CustomTkinter 6.0.0) |
| 管理ツール manage_data.py | **PC確認済み**(Linux) |
| GPIO 制御(gpiozero の仮想ピン MockFactory) | **PC確認済み(仮想ピンのみ)** |
| RC-S380 読み取り(偽の nfc モジュールで処理の流れのみ) | **実装済み・実機未確認** |
| GPIO → リレー → 電磁ロック LE-53 の実動作 | **実装済み・実機未確認** |
| Windows 11 / Python 3.14 / PowerShell での実行 | **未確認**(Windows 固有の処理は避けた実装です) |
| Raspberry Pi 4 / Debian 13 / Python 3.13.5 での実行 | **未確認** |

画面イメージ(デモモードで実際にキャプチャしたもの)は `docs/screenshots/` にあります。

---

## 1. フォルダ構成

```
camera_rental_system/
├── main.py                  アプリ起動ファイル
├── config.py                設定ファイル(デモ/実機、GPIO番号、貸出時間 など)
├── manage_data.py           管理ツール(利用者・カメラの登録など)
├── self_test.py             自己診断テスト(SELF TEST: OK と表示)
├── requirements.txt         Windows(デモ)用ライブラリ
├── requirements-pi.txt      Raspberry Pi(実機)用ライブラリ
├── camera_rental/
│   ├── errors.py            エラーと利用者向けメッセージ
│   ├── models.py            データの入れ物(利用者・カメラ・貸出)
│   ├── database.py          SQLite の読み書き
│   ├── rental_service.py    貸出・返却の手続き(DB記録 → 解錠 の順番を守る)
│   ├── app_logging.py       ログ設定
│   ├── hardware/
│   │   ├── __init__.py      デモ用/実機用の切り替え
│   │   ├── card_reader.py   RC-S380(nfcpy)とデモ用リーダー
│   │   └── lock_controller.py  GPIO(gpiozero)とデモ用ロック
│   └── gui/
│       ├── app.py           メインウィンドウ・画面切替・タイムアウト
│       ├── theme.py         色・文字・大きさ
│       ├── widgets.py       共通部品
│       ├── screens_flow.py  貸出・返却の流れの画面
│       └── screens_info.py  貸出状況・履歴の画面
├── tools/
│   ├── check_card_reader.py RC-S380 単体確認
│   └── check_lock.py        GPIO(電磁ロック)単体確認
├── tests/                   自動テスト(unittest)
└── docs/DESIGN.md           設計書
```

実行すると次のフォルダが自動で作られます。

| フォルダ | 中身 |
|---|---|
| `data/` | SQLite ファイル(実機用 `camera_rental.sqlite3` / デモ用 `demo_camera_rental.sqlite3`) |
| `exports/` | CSV 出力 |
| `logs/` | ログ(`camera_rental.log`、1MB ごとに切り替え・5世代保存) |

---

## 2. Windows でデモ起動する

PowerShell で、このフォルダに移動してから実行します。

```powershell
# 1. 仮想環境を作る(最初の1回だけ)
py -m venv .venv

# 2. 仮想環境を有効にする
.\.venv\Scripts\Activate.ps1
#   「スクリプトの実行が無効」と出た場合は、次を1回だけ実行してから再度有効化
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 3. ライブラリを入れる(最初の1回だけ)
pip install -r requirements.txt

# 4. 自己診断テスト
python self_test.py
#   最後に「SELF TEST: OK」と出れば成功

# 5. デモモードで起動
python main.py --demo
```

### デモの操作

1. ホームで「カメラを借りる」を押す
2. 社員証の画面で、黄色い枠の **デモ用ボタン**(例:「森 航太郎」)を押す
   = 社員証をかざしたことになります
3. カメラと貸出時間を選んで「確認へ進む」→「貸出を確定する」
4. 「扉のロックを開けました」→ 完了 → ホームに自動で戻る
5. 「カメラを返す」→ 同じ人のデモボタン →「返却する」

デモ用の利用者(`config.py` の `DEMO_USERS`):

| ボタン | 用途 |
|---|---|
| デモ 太郎 / 森 航太郎 | 通常の利用者 |
| 利用停止 花子 | 「利用停止中」のエラー確認 |
| 未登録カード | 「登録されていない社員証」のエラー確認 |

その他の確認方法:

```powershell
# 解錠失敗の画面(再試行・取消・管理者連絡)を確認する
#   1回目の解錠は失敗、再試行すると成功します(以後くり返し)
python main.py --demo --demo-unlock-fail

# デモのデータを最初からやり直す(アプリを閉じてから)
Remove-Item data\demo_camera_rental.sqlite3
```

デモモードでも **SQLite への保存は実際に行います**。
アプリを閉じて再起動しても、貸出状況と履歴が残っていることを確認できます。

---

## 3. 管理ツール(利用者・カメラの登録)

一般利用者がタッチ画面から誤って操作できないよう、登録・変更はコマンドで行います。

```powershell
python manage_data.py add-user 10002 "森 航太郎" 012E4CAA12345678
python manage_data.py add-camera "セキュアカメラ2号機"
python manage_data.py list-users
python manage_data.py list-cameras
```

| コマンド | 内容 |
|---|---|
| `add-user 社員番号 氏名 カードID [--disabled]` | 利用者登録(重複はエラー) |
| `add-camera カメラ名` | カメラ登録(重複はエラー) |
| `list-users` / `list-cameras` | 一覧表示 |
| `disable-user 社員番号` / `enable-user 社員番号` | 利用停止 / 再開 |
| `set-camera-status カメラID maintenance` | 点検中にする(`available` で貸出可能に戻す) |
| `list-rentals [--active]` | 履歴(`--active` で未返却のみ) |
| `force-return 貸出ID` | 管理者返却(解錠はしない) |
| `export-history [--output ファイル名]` | 履歴を CSV 出力 |
| `unlock-logs` | 解錠の成功・失敗ログ |
| `check` | カメラ状態と貸出記録の食い違いチェック |

**対象のデータベース**は `config.py` の `DEMO_MODE` で決まり、毎回画面に表示されます。
明示する場合は、コマンドの前に `--real`(実機用)または `--demo`(デモ用)を付けます。

```powershell
python manage_data.py --real list-users
```

カードIDは区切り文字(空白・コロン・ハイフン)を除いて大文字にそろえて保存します。
`01:2e:4c:aa` と `012E4CAA` は同じカードとして扱います。

---

## 4. 設定(config.py)

よく変更する項目:

| 設定 | 初期値 | 内容 |
|---|---|---|
| `DEMO_MODE` | `True` | デモ/実機の切り替え(起動時の `--demo` / `--real` が優先) |
| `RENTAL_HOURS_OPTIONS` | `[1, 2, 4, 8]` | 貸出時間の候補(時間)。ここを変えるだけで画面のボタンが変わります |
| `LOCK_GPIO_PIN` | `18` | 電磁ロック用リレーの GPIO 番号(BCM) |
| `UNLOCK_SECONDS` | `10` | 解錠しておく秒数 |
| `LOCK_ACTIVE_HIGH` | `True` | `False` で active low の回路に対応 |
| `CARD_TARGETS` | FeliCa / Type A / Type B | 読み取るカードの種類 |
| `CARD_READ_TIMEOUT_SECONDS` | `30` | 社員証を待つ秒数 |
| `IDLE_TIMEOUT_SECONDS` | `60` | 無操作でホームに戻るまでの秒数 |
| `FULLSCREEN` | `False` | 全画面表示(Esc で解除) |
| `ALLOW_CSV_EXPORT_FROM_SCREEN` | `True` | 履歴画面に CSV ボタンを出すか |
| `LOGO_IMAGE_PATH` | `None` | 正式なロゴ画像がある場合のみ指定(ない場合は文字表示) |

---

## 5. Raspberry Pi への導入

> ここから先は **実装済み・実機未確認** の手順です。
> 実機で1つずつ確認しながら進めてください。

### 5-1. OS の準備

```bash
sudo apt update
sudo apt install -y python3-venv python3-tk python3-lgpio python3-gpiozero \
                    libusb-1.0-0 fonts-noto-cjk
```

- `python3-tk` : CustomTkinter が使う tkinter
- `python3-lgpio` / `python3-gpiozero` : GPIO 制御(Pi 4 + Debian 13 では lgpio が使われます)
- `fonts-noto-cjk` : 日本語フォント(ないと文字化けします)

**時刻の注意**: Raspberry Pi 4 には時計用電池(RTC)がありません。
ネットワークで時刻合わせ(NTP)ができない環境では、起動時に時刻がずれて
貸出日時・返却予定が正しく記録されません。
`timedatectl` で `System clock synchronized: yes` を確認するか、RTC モジュールを追加してください。

### 5-2. プログラムの配置

```bash
cd ~
# プログラム一式を ~/camera_rental_system に置く
cd camera_rental_system

# apt で入れた lgpio を使うため --system-site-packages を付ける
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements-pi.txt

python self_test.py      # SELF TEST: OK を確認
```

### 5-3. RC-S380 の確認

```bash
python -m nfc
```

表示される案内に従います。代表的な内容:

- **権限がない**(Permission denied など)→ udev ルールを追加し、`plugdev` グループに参加
  ```bash
  sudo sh -c 'echo SUBSYSTEM==\"usb\", ACTION==\"add\", ATTRS{idVendor}==\"054c\", ATTRS{idProduct}==\"06c3\", GROUP=\"plugdev\" >> /etc/udev/rules.d/nfcdev.rules'
  sudo udevadm control -R
  sudo adduser $USER plugdev
  # USB を挿し直し、ログインし直す
  ```
  ※ `06c3` は RC-S380/P、`06c1` は RC-S380/S です。`lsusb` で実際の ID を確認してください。
- **カーネルドライバー port100 が使用中** → `python -m nfc` が表示する
  `modprobe -r` と blacklist の手順に従います。

単体確認プログラム:

```bash
python tools/check_card_reader.py
```

社員証をかざすと、カードの種類とカードIDが表示されます。

```
カードの種類 : Type3Tag  (...)
カードID     : 012E4CAA12345678
登録状況     : 未登録(または DB 未作成)
```

このカードIDを `manage_data.py --real add-user` で登録します。
**同じ社員証を何回かかざして、毎回同じIDになるか必ず確認してください。**
(読むたびにIDが変わるカードは、このシステムでは使えません。docs/DESIGN.md「9. リスク」参照)

#### カードIDについて

nfcpy の `tag.identifier` をそのまま16進数文字列にしています。中身はカードの種類で異なります。

| カードの種類 | 取得される値 |
|---|---|
| FeliCa(Type3Tag) | IDm(8バイト = 16文字) |
| MIFARE などの Type A | UID(4 / 7 / 10 バイト) |
| Type B | PUPI(4バイト) |

- スマートフォンのタッチ決済など、ランダムな UID を返すカードがあります。
- IDm / UID はカードを区別するための番号で、暗号的な本人確認ではありません。
- 社員証の仕様によっては、カード内のデータ(社員番号など)を読む方式の方が適切な場合があります。
  その場合は `card_reader.py` の `_wait_for_card()` だけを変更すれば、他の部分はそのまま使えます。
- RC-S380 の後継機 RC-S300 は nfcpy では使えません。

#### Windows で RC-S380 を使う場合(任意)

デモモードには不要です。Windows で実機確認したい場合のみ、Zadig で RC-S380 のドライバーを
WinUSB に変更し、`pip install nfcpy` します。
変更すると Sony の NFC ポートソフトウェアでは使えなくなります(元に戻すにはデバイスマネージャーで操作)。

### 5-4. GPIO(電磁ロック)の確認

**必ず「6. 安全上の注意」を読んでから行ってください。**

1. まず **電磁ロックをつながず**、GPIO18 に LED(330Ω程度の抵抗付き)またはテスターをつなぐ
2. 流れだけ確認(GPIO 出力なし)
   ```bash
   python tools/check_lock.py --dry-run --seconds 3
   ```
3. 実際に出力して LED / テスターで確認
   ```bash
   python tools/check_lock.py --seconds 3
   ```
   解錠中に LED が点く(または 3.3V が出る)→ 施錠で消えることを確認します。
4. リレーモジュールをつないで、リレーの動作音・表示LEDを確認
   - リレーモジュールが **active low**(Low で ON)の場合:
     ```bash
     python tools/check_lock.py --seconds 3 --active-low
     ```
     動作が合ったら `config.py` の `LOCK_ACTIVE_HIGH = False` にします。
   - **起動直後にリレーが ON になる場合は active high / low の設定が逆です。** すぐに止めて見直してください。
5. 最後に、別電源・リレー経由で電磁ロックをつないで確認

### 5-5. 実機モードで起動

```bash
python manage_data.py --real add-camera "セキュアカメラ1号機"
python manage_data.py --real add-user 10002 "森 航太郎" 012E4CAA12345678

python main.py --real --fullscreen
```

`config.py` を `DEMO_MODE = False`、`FULLSCREEN = True` にしておけば、`python main.py` だけで起動します。

電磁ロックの初期化に失敗した場合でもアプリは起動し、ホーム画面に
「電磁ロックが使用できないため、貸出・返却を停止しています」と表示して貸出・返却を止めます。

### 5-6. 自動起動(任意・未確認)

デスクトップにログインしたときに起動する例(XDG autostart):

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/camera-rental.desktop
```

```ini
[Desktop Entry]
Type=Application
Name=Camera Rental
Exec=/home/ユーザー名/camera_rental_system/.venv/bin/python /home/ユーザー名/camera_rental_system/main.py --real --fullscreen
Path=/home/ユーザー名/camera_rental_system
```

あわせて、`sudo raspi-config` → Display Options → Screen Blanking で画面の自動消灯を無効にしてください。

---

## 6. 安全上の注意(電磁ロック)

- **電磁ロックを Raspberry Pi の GPIO に直接つないではいけません。**
  GPIO は 3.3V・数mA しか出せず、電磁ロックを直接つなぐと Raspberry Pi が壊れます。
- **リレーモジュール、または適切な MOSFET 回路を使ってください。**
  MOSFET の場合は 3.3V のゲート電圧で十分にONになるロジックレベル品を選びます。
- **フライバックダイオードを使ってください。**
  電磁ロック(コイル)を OFF にした瞬間に高い逆電圧が発生します。
  コイルと並列に、逆向きにダイオード(例: 1N4007 など)を入れて回路を保護します。
  リレーモジュールに内蔵されているのは「リレーのコイル用」で、電磁ロック側には別途必要です。
- **ロック用には別電源を使ってください。**
  Raspberry Pi の 5V / 3.3V ピンから電磁ロックの電力を取ってはいけません。
  GND の共通化が必要かどうかは回路方式(リレー / MOSFET)によって異なります。
- **定格電圧と電流を確認してください。**
  LE-53 の定格電圧・消費電流・**連続通電時間**をデータシートで確認し、
  電源・リレー接点・MOSFET・配線がそれを上回る容量であることを確認してください。
  `UNLOCK_SECONDS`(初期値 10秒)が連続通電の定格を超えないようにしてください。
- **最初は LED またはテスターで GPIO 出力を確認してください。**(5-4 の手順)
- **active high / active low を実際の回路に合わせてください。**
  市販のリレーモジュールは active low のものが多いです。
  設定が逆だと「普段は解錠、貸出時だけ施錠」という危険な動作になります。
- **停電・故障時の扱いを決めてください。**
  通電で解錠するタイプ(通電解錠)なら、停電時は施錠のままです。
  非常時にカメラを取り出す方法(物理キーなど)を管理者側で用意してください。
- 配線作業は必ず電源を切ってから行い、電気工事の資格が必要な作業(AC 100V の配線など)は有資格者に依頼してください。

---

## 7. 自動テスト

```powershell
python self_test.py            # 結果のみ
python self_test.py --verbose  # テストごとの結果
```

ハードウェアなしで、DB作成・テーブル作成・利用者/カメラ登録・カード検索・貸出・状態変更・
二重貸出防止・返却・履歴保存・CSV・接続終了・**一時DBの削除(WinError 32 対策)**・
**DB記録失敗時に解錠しないこと** などを確認します(78件)。

gpiozero が入っていない環境(Windows など)では、GPIO 仮想ピンのテスト5件がスキップされます。

`pytest` を入れている場合は `pytest` でも実行できます。

---

## 8. トラブルシューティング

| 症状 | 確認すること |
|---|---|
| 文字が四角(豆腐)になる | Pi: `sudo apt install fonts-noto-cjk` |
| `No module named 'tkinter'` | Pi: `sudo apt install python3-tk`、Windows: Python インストーラーで「tcl/tk」を有効に |
| 「カードリーダーが見つかりません」 | `python tools/check_card_reader.py` のメッセージに従う |
| 「電磁ロックが使用できない」 | `logs/camera_rental.log` の詳細、`python tools/check_lock.py --dry-run` |
| 「データを保存できませんでした」 | `logs/camera_rental.log`、ディスクの空き容量、`data/` の書き込み権限 |
| 貸出中なのに記録がおかしい | `python manage_data.py check`、`unlock-logs` |
| 解錠失敗の問い合わせ | 画面の「受付番号」= 貸出ID。`list-rentals` と `unlock-logs` で確認 |
