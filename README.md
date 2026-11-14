# 銀土群團購對外公開資訊網站

網站：https://a50932a.github.io/ginhiji-buyer/

這一頁給買家看自己參與的團購進度、應收與未付。金額是新台幣。頁首的「資料更新於」是**上次手動同步後公開內容有變化**的時間。網站不會自動更新。

## 公開資料長什麼樣子

`data/public.json` 是網站唯一的資料檔。`index.html` 用相對路徑讀它。形狀沿用原本頁面：

| 位置 | 公開欄位 |
| --- | --- |
| 團購 | id、名稱、來源、幣別、狀態、成立日、圖片 key、商品連結、收費匯率、費用名稱與金額、訂單 |
| 訂單 | 買家名稱、是否團主自留、商品台幣、費用台幣、應收、自留參考值、已收、未收、品項、收款 |
| 品項 | 名稱、單價、數量、狀態、寄件編號、圖片 key |
| 收款 | 金額、日期、備註、是否沿用既有抵扣標記 |
| 買家合計 | 由上面的非自留訂單加總 |
| 請款預告 | 只重算 `sync/billing_groups.json` 裡那些團的未付金額 |

應收、已收、未收使用來源 `settlement` 已經四捨五入的整數。程式不會用「外幣 × 收費匯率」再算一次。商品與費用的拆開數字只供畫面顯示，加總若與應收差 1 元，仍以應收整數為準。

圖片在同步時下載到 `img/l`（長邊 800）與 `img/t`（高 360）。瀏覽器不連訂單 API。

## 公開範圍

`sync/allowlist.json` 的 `include` 才會被同步。來源現在約有一百多團；清單以外的團不會讀進公開檔。

目前允許清單是：

- 這一頁原本已經公開的 140 團
- `01a1d8a326e773d9be07c6063788e9dd`（2026-11-13、人民幣、已截止的閒魚立牌團，購買人 Mita，應收 NT$4,070）

若某一筆不屬於這個站，從 `include` 刪掉即可，不需要改程式。下次手動同步才會反映。

請款預告只含 `sync/billing_groups.json` 的 `include`。條目可以是團購 id，或是 `{"id": "…", "buyers": ["買家"]}` 只把列出的購買人算進該團。沒寫 `buyers` 時，行為與原本相同，會列入該團所有未付的非自留訂單。付清的團或指定買家若已付清，會從預告消失；其他未付款團不會自動加進來。

來源收款沒有抵扣類型欄位，只有金額、日期與備註。`sync/offset_notes.json` 列出應標成抵扣的備註全文；同一筆收款若上一筆公開資料已標記為抵扣，也會沿用。兩者任一成立即顯示為抵扣，並計入買家對帳的 `off`／`offs`。訂單的已付金額沿用來源結算的已收整數，本身已包含這些抵扣；團購頁會在已付旁標出含抵扣多少。

`sync/buyer_aliases.json` 會在買家對帳與請款預告把同一人的不同名稱合併顯示。團購頁的訂單名稱維持來源原樣，不會寫回訂單系統。

## 不會公開的欄位

同步若在投影裡看到這些欄位，會直接中止，不覆蓋舊檔：

- `costRate`、成本、利潤、`costShare`
- 成員、角色、email
- 支付（payout）、卡片、銀行、權杖
- 訂單備註、品項備註、團購備註

自行吸收的費用（`absorb: true`）也不進公開費用列表。收費匯率 `chargeRate` 會留下，因為這一頁原本就顯示它。

## 既有風險

這個倉庫與 GitHub Pages 都是公開的，沒有登入。任何人都讀得到買家名稱、品項、單價、應收、已收、未付、收款備註與少數寄件編號。這是這一頁原本的公開方式，這次沒有再放大欄位，也沒有加上登入。

若買家之間不該互相看到未付金額或收款備註，需要另做存取控制。那不是這次同步能在靜態頁上補上的。

## 同步怎麼跑

只有手動執行才會更新。到 GitHub Actions 執行 `sync-orders`，或在倉庫根目錄執行：

```bash
pip install -r requirements.txt
ORDERS_API_TOKEN='權杖只放在這個環境' python3 -m sync.sync_orders
```

程式只讀環境變數 `ORDERS_API_TOKEN`，不讀 `~/.config/money-orders/token`。權杖不要寫進前端、倉庫或日誌。

工作流程用 `GET` 讀取：

- `/api/orders/group-buys`
- `/api/orders/group-buys/{id}`
- `/api/orders/items?groupBuyId=`
- `/api/orders/buyers/summary?ids=`

請求帶 `User-Agent: money-orders-agent/1.0` 與 `Authorization: Bearer`。權杖只會加在 `money.klab.tw`；圖片若被轉到別的主機，不會帶授權。內網位址會被拒絕。

內容與上一筆公開檔相同就結束，不提交。來源 401、403、連線失敗、結算對不上、買家總覽對不上，或是回應裡出現不公開欄位時，程式結束且不改 `data/public.json`。先前已公開、但這次清單裡消失的團也不會被刪掉。

內容有變化時，工作流程會提交公開檔並請求 GitHub Pages 重建。成功時印出 `updated`；內容相同印出 `noop`。來源拒絕授權、連線失敗或結算對不上時，不改上一筆公開資料。

## 若要改由審查過的投影做一次匯入

正式路徑是上面的 API。若短期只能提供一份已拿掉內部欄位的檔案，可以用：

```bash
python3 -m sync.sync_orders --projection /路徑/在倉庫外/reviewed.json
```

檔案裡只要出現成本匯率、利潤、成員、支付、email、權杖或卡片欄位，程式會拒絕。不要把這份檔提交進倉庫。外層要是：

```json
{
  "groups": [{ "groupBuy": {}, "orders": [], "fees": [], "settlement": { "orders": [] } }],
  "items": { "<團購 id>": [] },
  "buyers": []
}
```

`items` 必須只含該團。若 `/items` 回應裡出現別團的品項，同步會中止。每團只留：

- `groupBuy`：`id`、`name`、`source`、`currency`、`status`、`startedAt`、`url`、`image`、`chargeRate`
- `fees`：`name`、`amount`、`currency`、`absorb`
- `orders`：`id`、`buyerName`、`isSelf`、`items`、`payments`
- `items`：`id`、`name`、`unitPrice`、`quantity`、`status`、`shippingNumber`、`image`
- `payments`：`amount`、`paidAt`、`note`
- `settlement.orders`：`orderId`、`goodsCharge`、`feeCharge`、`charge`、`paidSum`、`remaining`
- 另附每個團的 `/items` 陣列，以及 `/buyers/summary?ids=` 的買家列（`name`、`charge`、`paidSum`、`remaining`、`isSelfOnly`）

`charge`、`paidSum`、`remaining` 必須是來源已經四捨五入的整數。
