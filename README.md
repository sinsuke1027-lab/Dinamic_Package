# ダイナミックプライシング MVP

旅行代理店向けのダイナミックプライシング・パッケージングシステム。

## プロジェクト構成

```
Dinamic_Priceing/
├── backend/          # FastAPI バックエンド
│   ├── main.py       # APIエンドポイント
│   ├── models.py     # DBモデル
│   ├── schemas.py    # Pydanticスキーマ
│   ├── pricing.py    # 価格計算エンジン（コア）
│   ├── database.py   # DB接続設定
│   └── requirements.txt
└── frontend/         # Next.js フロントエンド
    ├── app/
    │   ├── page.tsx          # 商品一覧（Opaque Pricing）
    │   ├── checkout/page.tsx # 決済画面（カウントダウン）
    │   └── admin/page.tsx    # 在庫管理（管理者）
    ├── components/Navbar.tsx
    ├── lib/api.ts            # APIクライアント
    └── package.json
```

---

## 🚀 起動方法

### バックエンド（ターミナル 1）

```bash
cd backend

# 初回のみ：仮想環境の作成とパッケージインストール
python -m venv venv
source venv/bin/activate          # Mac/Linux
# .\venv\Scripts\activate         # Windows

pip install -r requirements.txt

# 起動
uvicorn main:app --reload
# → http://localhost:8000 で起動
# → http://localhost:8000/docs でSwagger UIが確認できる
```

### フロントエンド（ターミナル 2）

```bash
cd frontend

# 初回のみ：パッケージインストール
npm install

# 起動
npm run dev
# → http://localhost:3000 で起動
```

---

## 📄 主要ページ

| URL | 説明 |
|---|---|
| `http://localhost:3000` | 商品一覧（Opaque Pricing UI） |
| `http://localhost:3000/checkout?token=XXX` | 決済確認（カウントダウンタイマー） |
| `http://localhost:3000/admin` | 在庫管理（管理者用） |
| `http://localhost:8000/docs` | APIドキュメント（Swagger UI） |

---

## 💡 コア機能

1. **リスク在庫管理**: `/admin` から在庫の追加・削除・席数の更新が可能
2. **シャドープライス**: 残席率に基づいて価格が自動計算（残席が少ないほど高価格に）
3. **Opaque Pricing**: 商品一覧・決済画面では**総額のみを表示**（内訳は非表示）
4. **カウントダウンタイマー**: 決済画面で**15分**のタイマーが動作。0になると自動リダイレクト

---

## 🛠 サンプルデータ追加（curlコマンド）

```bash
curl -X POST http://localhost:8000/admin/inventory \
  -H "Content-Type: application/json" \
  -d '{
    "name": "沖縄3泊4日パック",
    "category": "ツアー",
    "total_seats": 10,
    "booked_seats": 7,
    "base_cost": 80000,
    "floor_price": 70000,
    "description": "那覇空港発着・ホテル・観光ツアー込み",
    "expires_at": "2026-12-31T23:59:59"
  }'
```
