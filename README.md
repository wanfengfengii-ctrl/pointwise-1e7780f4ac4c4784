# 材料试验室读板交班

白班仪器员登记读板，交班员选择试盘并暂时遮蔽待复检的盘。夜班复检员只带固定交换件和纸质复测单工作。次班核账员凭旧件号和复检成果号分别领取明细与计量账。

需要 Python 3.11，仅使用标准库和 SQLite。在项目目录运行控制台提供的正常回归入口。演示从 `examples/` 读取板录和纸单，使用独立临时库并打印两个成果的实际 CSV。

```text
python3 -B check_project.py
python3 -B demo.py
```

原测试同时可用 `python3 -B -m unittest discover -s tests -t . -p 'test_*.py'` 直接运行。

## 一次交班

1. 仪器员交出批号、清册和按读取顺序排列的原行。
2. 登记核对每个清册槽都有唯一原行，以原行在数组中的一基位置记录出处。相同批号和完整有序内容重投领取原号。显式仪器更正为该批号追加修订，旧号仍可领取。
3. 交班员凭修订号选盘并登记遮蔽，取得冻结号。盘序沿用清册，槽按原号码的数字顺序出表。
4. 白班按冻结号发行，取得固定件和发行回执。同一冻结号可再次发行新件。
5. 夜班关闭源库，只凭交换件接纳。接纳号与初始账同时固定，同件重办返回已有绑定。
6. 夜班按原盘、原槽提交纸质改值单并指定撤遮盘。遮蔽盘上的实测同样可改值。撤遮只改变可见性，显示本单的生效值或发行原值。
7. 复检成果、明细、盘账和成功回执一同提交。失败后可使用同一输入重办。
8. 次班在仪器修订更新后重开离线库，按最初件号和本次复检成果号领取、导出各自的固定账。

样例中甲/2 为 7，乙/2 为 13，乙/3 是真空。乙带遮蔽发行。只撤遮领到乙/2 的 13 和乙/3 的空值；纸单把乙/2 改成 17 并撤遮时，甲乙各计一槽，合计分别为 7 和 17。旧号始终显示乙盘遮蔽，旧号的乙盘计数和合计都是零。

## Python 接口

| 调用 | 参数和结果 |
| --- | --- |
| `intake.repository.open_source(path)` | 打开或初始化源库，返回 SQLite 连接。 |
| `intake.register.register(db, batch, inventory, rows, correction=False)` | 清册项为 `plate, slots`，原行项为 `plate, slot, value`，返回固定修订号。`correction` 是关键字参数。 |
| `selection.freeze.stage(db, revision_id, plates, masked=())` | 返回冻结选择号。选盘与遮蔽使用原盘名。 |
| `exchange.issue.issue(db, selection_id)` | 返回 `IssuedPiece`，包含件号、正文和 `receipt`。用 `exchange.contract.encode_envelope(piece)` 交付 JSON 文本。`exchange.read.get_issued_piece` 可按件号原样领取。 |
| `exchange.accept.open_offline(path)` | 打开或初始化离线库，返回 SQLite 连接。 |
| `exchange.accept.accept(db, payload)` | 接收 JSON 文本或 UTF-8 字节，返回带 `acceptance_id` 与原件的 `AcceptedPiece`。`exchange.read.get_accepted_piece` 可按接纳号领取。 |
| `review.amend.amend(db, acceptance_id, changes=(), reveal=())` | 改值项为 `plate, slot, value`，撤遮项为盘名，返回带 `result_id` 和成功回执的 `ReviewResult`。每张纸单以指定接纳件为起点，独立签出。 |
| `ledger.readback.read(db, result_id, view='rows')` | 以件号领初始账，以复检成果号领复检账。`rows` 返回带修订号和原行号的明细，`totals` 返回每盘的遮蔽状态、计数、合计。 |
| `ledger.export.export_ledger(db, result_id, view='rows')` | 读取同一固定账并返回可写为 UTF-8 的 CSV 文本。 |

按盘披露核账（V2）见 `DISCLOSURE.md`：`exchange.issue.issue_disclosure`、`exchange.issue.disclose_plate`、`exchange.accept.accept_disclosure`、`ledger.readback.read_disclosure`。V2 与原 V1 接口、旧件及历史账并存，共用原 `open_source` / `open_offline`。

公开板录、选盘和纸单的序列使用列表或元组。标识为非空可打印文本，首尾无空白。槽号为正整数，盘名和槽号共同确定槽身份。清册可以列一个无槽的盘。每个已声明的真空槽须有一条 `value=None` 的原行。实测与改值使用 Python 整数，布尔值和浮点值被拒绝。选盘、遮蔽、撤遮及纸单中的同一改值目标各自不得重复。对已可见盘撤遮保持该盘可见。

交换件外层字段为 `version`、`kind`、`piece_id`、`body` 和 `receipt`。版本为 1，类别为 `material-plate-piece`。正文含修订号、冻结号、批号、所选盘、遮蔽盘及完整槽表。槽号、原行号和实测值用规范十进制字符串传递，真空值用 JSON `null`。接纳核对有序槽身份、盘范围和遮蔽关系、收据绑定及正文 SHA-256。交接渠道负责发行方身份，摘要用于检查内容一致性。展示遮蔽只约束明细和核账的输出，交换件应交给有权处理完整槽材料的复检员。

计数和合计只统计可见实测，零值计一槽，真空仍可在可见明细和导出中查到。单位沿用仪器原单位，SQLite 中账快照采用十进制文本保持整数精度，导出不经浮点转换。固定输入得到相同的明细顺序、出处和数值，各次签出的号码独立分配。

打开源库或离线库只创建缺少的结构，重复执行保留已提交的业务材料。调用方关闭连接，写入入口拥有各自的事务。无效登记、冻结、发行、接纳和复检分别报告 `RegistrationError`、`SelectionError`、`IssueError`、`AcceptError` 和 `AmendError`。未知成果号报告 `UnknownResultError`，未知原件或接纳号的直接领取报告 `UnknownPieceError`。写入前的读取失败与提交失败均保留已有成果，失败的范围内无部分成果或成功回执。
