# TikTok Lite・ポイ活 話題収集LINE BOT（無料試作版）

X、Threads、Instagramの公開検索に現れた「TikTok Lite」「TikTok関連のポイ活」の新着話題を集め、6時間ごとにLINEへまとめて通知します。

## このBOTでできること

- 1日4回、日本時間の03:17・09:17・15:17・21:17ごろに自動巡回
- X、Threads、Instagramをサービス別に整理
- 同じ話題を二重通知しない
- 「増額」「キャンペーン」「招待」「改悪」「不具合」などを優先表示
- 新着が0件ならLINEを送らず、無料メッセージ枠を節約
- GitHub Actionsで動くため、常時起動するパソコンは不要
- 外部Pythonパッケージ不要

## 無料試作版について（重要）

この版は各SNSにログインせず、Bingの公開Web検索RSSとGoogleニュースの公開RSSから候補を集めます。SNS画面の直接スクレイピングやログイン自動操作は行いません。

そのため、次の制約があります。

- 検索サイトに掲載されていない投稿は取得できません
- 投稿の発見が数時間〜数日遅れる場合があります
- 非公開投稿は取得できません
- 特にThreadsとInstagramはXより取得件数が少ない場合があります
- 「全投稿を漏れなく収集」するものではありません

まず無料で反応を見る試作版です。精度を上げたくなったら、Threads・InstagramのMeta公式APIやX公式APIを追加できます。

---

## 設定は大きく2段階

1. LINE公式アカウントを無料で作る
2. GitHubに2つの秘密情報を登録する

秘密情報はコード内に書かず、GitHub Secretsに保存します。

## ① LINE公式アカウントを準備

### 1. LINE公式アカウントを作る

[LINE Official Account Manager](https://manager.line.biz/)へLINEアカウントでログインし、新しい公式アカウントを作成します。

料金プランは月額0円の「コミュニケーションプラン」で大丈夫です。現在の無料枠は月200通です。

### 2. Messaging APIを有効にする

作成した公式アカウントを開き、次の順に進みます。

**設定 → Messaging API → Messaging APIを利用する**

途中で「プロバイダー」の作成を求められたら、自分で分かる名前を入力します。例：TikTok話題BOT

### 3. BOTを友だち追加する

[LINE Developers Console](https://developers.line.biz/console/)を開きます。

作成したプロバイダー → Messaging APIチャネル → Messaging API設定の順に開き、表示されるQRコードから自分のBOTを友だち追加します。

友だち追加していないとPush通知を受け取れません。

### 4. チャネルアクセストークンを取得する

同じMessaging API設定画面を下へ進み、チャネルアクセストークンを発行してコピーします。

これをGitHubへ次の名前で登録します。

**LINE_CHANNEL_ACCESS_TOKEN**

トークンはパスワードと同じ扱いです。スクリーンショットやSNSに載せないでください。

### 5. 自分のユーザーIDを取得する

LINE Developers Consoleのチャネル基本設定を開き、あなたのユーザーIDをコピーします。

Uから始まる33文字です。普段友だち検索に使う「LINE ID」とは別物です。

これをGitHubへ次の名前で登録します。

**LINE_USER_ID**

---

## ② GitHubへアップロード

### 1. ZIPを解凍する

このBOTのZIPを解凍します。GitHubにはZIPそのものではなく、解凍後の中身をアップロードしてください。

### 2. 新しいリポジトリを作る

GitHubで新規リポジトリを作ります。名前の例：

**tiktok-lite-topic-bot**

公開・非公開はどちらでも動きます。秘密情報はGitHub Secretsに入るため、公開リポジトリでもコード上には表示されません。

### 3. 全ファイルをアップロードする

解凍したフォルダの中身を、そのままリポジトリの一番上へアップロードします。

次のファイル・フォルダが見えればOKです。

- .github/workflows/topic-bot.yml
- data/
- tests/
- bot.py
- config.json
- README.md

.githubは先頭に点が付いたフォルダです。これが欠けると自動実行されません。

### 4. GitHub Secretsを2つ登録する

リポジトリ画面で次の順に進みます。

**Settings → Secrets and variables → Actions → New repository secret**

1つ目：

- Name：LINE_CHANNEL_ACCESS_TOKEN
- Secret：LINEでコピーしたチャネルアクセストークン

2つ目：

- Name：LINE_USER_ID
- Secret：Uから始まる自分のユーザーID

名前は大文字・小文字を含め、完全に同じにしてください。

---

## ③ LINE接続テスト

1. GitHubリポジトリ上部のActionsを開く
2. 左側の「TikTok Lite 話題BOT」を選ぶ
3. Run workflowを押す
4. 「LINE接続テストだけを送る」にチェックを入れる
5. 緑色のRun workflowを押す

少し待って、LINEに次のような通知が来れば接続成功です。

> ✅ TikTok Lite話題BOT  
> LINE通知の接続テストに成功しました。

次に、同じRun workflowからチェックを外して実行すると、実際の収集テストができます。

## 自動実行時刻

GitHub Actionsが次の時刻ごろに実行します。

- 03:17
- 09:17
- 15:17
- 21:17

すべて日本時間です。GitHub側の混雑により、開始が数分〜数十分遅れることがあります。

新着がなければLINEは送信しません。新着が毎回あった場合でも、1人への通知は最大1日4回、31日で124通です。接続テストなどを含めても、通常は無料枠の月200通以内に収まります。

GitHub Freeには非公開リポジトリ用のActions実行時間も月2,000分含まれます。このBOTは短い処理を1日4回だけ行うため、通常は無料枠内です。ただし、他のGitHub Actionsと無料枠を共有している場合は利用状況を確認してください。公開リポジトリの標準Actions実行は無料です。

## 検索語を変更する

config.jsonのkeywordsを編集します。文字列を増やす場合は、前の行末のカンマを忘れないでください。

例：

    "keywords": [
      "TikTok Lite",
      "ティックトックライト",
      "TikTok Lite 招待",
      "TikTok Lite 増額"
    ]

優先表示したい言葉と点数はscore_termsで変更できます。点数が大きいほど上へ表示されます。

## 通知済みデータ

- data/state.json：通知済み判定用のデータ
- data/latest.json：最後に取得した結果とエラー情報

BOTが自動更新します。通常は手動編集しないでください。

## よくあるトラブル

### LINEが届かない

- BOTを友だち追加したか確認
- LINE_CHANNEL_ACCESS_TOKENの名前と内容を確認
- LINE_USER_IDがUから始まる33文字か確認
- LINE公式アカウントをブロックしていないか確認

### Actionsが赤い×になる

赤い実行履歴を開き、赤くなっている工程を確認します。エラー文は日本語で出るようにしてあります。

### git pushの権限エラーが出る

GitHubで次を開きます。

**Settings → Actions → General → Workflow permissions**

Read and write permissionsを選び、保存してからもう一度実行します。

### 話題が0件になる

故障とは限りません。無料版は公開検索に掲載された投稿だけが対象です。数回動かしても極端に少ない場合は、config.jsonの検索語を増やすか、公式API版への更新を検討してください。

## 公式資料

- [LINE Messaging APIを始める](https://developers.line.biz/en/docs/messaging-api/getting-started/)
- [LINEのPushメッセージ](https://developers.line.biz/en/docs/messaging-api/sending-messages/)
- [LINEユーザーIDの確認方法](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)
- [LINE公式アカウント料金プラン](https://www.lycbiz.com/jp/service/line-official-account/plan/)
- [GitHub Actionsの料金と無料枠](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

## セキュリティ上の注意

- チャネルアクセストークンをコードや画像に貼らない
- GitHub Secretsの値を他人に送らない
- トークンが漏れた疑いがある場合は、LINE Developers Consoleで再発行する

## ライセンス

MIT License
