# 按盘披露核账

`README.md` 说明现有整件交班、离线接纳、纸单复检及固定账。V1 的遮蔽只控制出表，交换件携带完整槽表。新链路供分班核账使用，由发行员决定本班获准领取的盘。V2 交付范围为整盘披露及核账，授权决策和可信凭据交接由调用方负责。

## Python 接口

| 调用 | 参数和结果 |
| --- | --- |
| `exchange.issue.issue_disclosure(db, selection_id)` | 使用 `open_source` 打开的源库及已冻结选择，返回 `(issue_id, credential)`。每次成功发行产生新号，即使使用相同的冻结选择。 |
| `exchange.issue.disclose_plate(db, issue_id, plate)` | 以源库、发行号和获准的原盘名返回一个 `payload`。盘须属于该次发行的冻结范围。重开源库或追加仪器更正后，同号仍可补发固定盘件。 |
| `exchange.accept.accept_disclosure(db, credential, payload)` | 使用 `open_offline` 打开的独立离线库、另路取得的可信凭据及单盘件，返回字符串核验号。 |
| `ledger.readback.read_disclosure(db, audit_id)` | 在离线库中按核验号返回当次成功接纳后的固定账，结构见下。 |

`stage` 的冻结盘范围及清册顺序用于本次发行。初始遮蔽继续用于 V1 出表。V2 的发行员获准后可以调用 `disclose_plate` 取得冻结范围内的任何一盘。继续用原 `open_source`、`open_offline` 初始化或重开库。已存在的 V1 库、接口、旧件、复检及历史账继续可用。

## 两路交付

`credential` 和 `payload` 是可经 JSON 往返的字典，对象字段顺序没有业务含义。可信渠道交付 `credential`，普通交接渠道提交 `payload`。接纳端凭独立收到的 `credential` 做判断，须能在源库关闭时完成核验。

- `credential` 的字段为 `version`、`issue_id`、`revision_id`、`plates`、`proof`。`version` 为整数 `2`，标识使用原名称规则。`plates` 是清册顺序的已选盘名列表。
- `payload` 的字段为 `version`、`issue_id`、`plate`、`rows`、`proof`。`version` 为整数 `2`。`rows` 为严格按数字槽号递增的列表，每行为 `{'slot': '2', 'value': '13', 'source_line': '4'}` 形状。槽号与一基原行号为正数，实测值为整数，沿用 V1 的规范十进制字符串。真空以 `value: null` 明示，无槽盘的 `rows` 为空列表。
- 两处 `proof` 的内部 JSON 对象由实现定义。接纳须用凭据认证盘位、固定发行及修订、完整槽表和逐行出处。遗漏真空槽、添加或重复槽、改值、改出处、错序、替换盘名、跨发行拼接或缺少有效证据均拒绝。

凭据可以公开所列标识、盘名、盘序和用于核验的证据。未获准盘的槽位、读值、原行出处和开启材料留在发行侧。取得另一盘所需的证据后，接收方仍不能凭已收到的材料离线验证对未披露盘低取值域读值的猜测。仅在发行成功提交后交付凭据。后续补发以当时固定的资料为准。

## 固定核验账

`read_disclosure` 返回 `{'issue_id': ..., 'revision_id': ..., 'plates': [...]}`。`plates` 沿可信凭据的盘序排出每一盘。未披露项为 `{'plate': '乙', 'status': 'undisclosed'}`。已核验项为 `{'plate': '乙', 'status': 'verified', 'rows': [...], 'count': 1, 'total': 13}`。读取结果的 `rows` 使用与单盘件相同的行字段及顺序，槽号、原行号、实测值返回 Python 整数，真空返回 `None`。修订出处由顶层 `revision_id` 与各行 `source_line` 共同给出。计数和合计沿用原单位与精确整数口径，真空保留明细且无贡献。已核验无槽返回空明细、计数零、合计零。实测零计一槽。

每次成功接纳新盘都固定同一发行当时已验真的盘集合及对应账，并产生新核验号。相同凭据下，同一盘的合法重投返回该盘首次接纳时的核验号，仍须验证重投的盘件。相同发行号绑定不同凭据时拒绝。发行之间分别累计。补收、修改调用方手中的返回对象以及重开库后，旧核验号仍返回原来范围和账。允许全量扫描及全量固定账。

无效发行请求、未知发行或盘及源端写入失败沿用 `IssueError`。无效凭据或盘件、绑定冲突及离线写入失败沿用 `AcceptError`。无效或未知核验号沿用 `UnknownResultError`。提交失败保持此前可领状态，失败范围内无新发行、盘接纳或核验成果。失败的盘件在排除故障后可重投。

## 调用夹具和核验

`disclosure_cases.stage_fixture(db)` 返回 `(revision_id, selection_id)`。样例的固定盘序为甲、乙、丙、丁。`EXPECTED_ROWS` 和 `EXPECTED_TOTALS` 给出全部盘验真后的手算结果。可运行 `python3 -B disclosure_cases.py`，在独立内存库里核对现有整件交班、裁剪拒绝、撤遮后的明细和历史账。这条命令只运行 V1。

用夹具从同一冻结号发两次。记住第一次的可信凭据，另取本次的甲件。断开源库，用凭据与甲件接纳。甲/2 值为 7、原行号为 2，其余盘未披露。补收第一次发行的乙件后，乙/2 为 13、原行号为 4，乙/3 为真空、原行号为 1，独立合计是计一槽、合计 13。再补丙、丁，丙的空明细计零，丁的实测零计一槽。重开并重投甲，返回甲首次核验号。分别读取首班账和补收后的账。

在乙首次接纳前，保留可信凭据，逐案尝试删乙/3、改原行号和使用另一次发行的乙件。拒绝后仍可领取甲的原账，随后原乙件可用。原测试辅助函数 `tests.support.deny_sql(db, sqlite3.SQLITE_TRANSACTION, 'COMMIT')` 可阻断保存时的提交，退出上下文后可重试。将发行重开、断源接纳、账册重开及原回归纳入联动验证。

交付说明需写明证据覆盖的盘事实、其他盘在交付中可见的信息，以及核验号固定范围的规则。继续使用 `.pointwise-runtime.json` 的现有运行格式，接通新旧核验并保留原回归。核验失败返回非零。演示打印实际核验账，显示断源补收前后两个核验号各自的披露范围。

## 本实现说明

- 证据覆盖的盘事实：`disclose_plate` 返回该盘整份槽表（数字槽号、实测值或真空、一基原行号）与开启材料。`credential.proof.root` 是对盘序内每盘承诺的 SHA-256 Merkle 根；每盘承诺是该盘槽表、`issue_id`、`revision_id`、盘名与随机盐的哈希。`payload.proof` 只提供该盘自己的盐、承诺及 Merkle 路径，足以把该盘固定到本次发行的根。
- 其他盘在交付中可见的信息：`credential` 只公开 `version`、`issue_id`、`revision_id`、盘序与根；`payload` 只含本盘的槽表与路径。未披露盘的槽号、读值、原行出处和开启盐都留在发行侧。接收方即使补齐其他盘的件，也无法凭已收到的材料离线验证对未披露盘低取值域读值的猜测：缺少该盘的盐，任何猜测都无法还原其承诺。
- 核验号固定范围：每次成功接纳新盘产生新 `audit_id`，其固定账沿 `credential` 盘序列出全部盘，已核验盘带 `verified` 明细、计数与合计，未披露盘为 `undisclosed`。同一凭据下同一盘合法重投返回首次核验号；已在账的较早核验号不随后续补收改变范围。相同发行号绑定不同凭据、跨发行拼接、篡改证据及提交失败都拒绝且不留部分成果。
- 交付路径：`exchange.disclosure` 定义严格格式与证据运算；`exchange/issue.py` 的 `issue_disclosure`/`disclose_plate` 落在源库，`exchange/accept.py` 的 `accept_disclosure` 与 `ledger/readback.py` 的 `read_disclosure` 落在离线库。随机盐使用 `secrets`，时间无关字段足够；测试断言只依赖结构与值，不依赖具体盐。
