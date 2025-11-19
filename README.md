# MySQL Binlog 分析恢复工具

一个强大的 MySQL Binlog 分析工具，支持 binlog 统计分析、数据恢复和闪回操作。

## 功能特性

- 📊 **Binlog 统计分析**: 生成详细的 binlog 操作统计报告
- 🔄 **数据恢复**: 从 DELETE 操作生成 INSERT 语句恢复数据
- ⚡ **闪回操作**: 支持多种闪回模式（deletes/inserts/updates）
- 🎯 **精确过滤**: 支持按时间、位置、数据库、表名过滤
- 🔧 **编码兼容**: 自动处理多种字符编码问题
- 📁 **灵活输出**: 支持控制台输出或保存到文件

## 安装要求

- Python 3.6+
- MySQL `mysqlbinlog` 工具（/usr/bin/mysqlbinlog）
- MySQL 开启ROW模式
- 访问 MySQL binlog 文件的权限

## 使用方法

### 1. 分析 Binlog 文件

生成 binlog 操作统计报告：

```bash
python binlog_tool_rollback.py analyze mysql-bin.000001
```

可选时间范围过滤：

```bash
python binlog_tool_rollback.py analyze mysql-bin.000001 "2025-11-17 00:00:00" "2025-11-17 23:59:59"
```

输出文件 `binlog_stats.txt` 包含以下信息：

* binlog 文件名
* 开始/结束时间
* 开始/结束位置
* INSERT/UPDATE/DELETE 操作计数
* 数据库和表名

### 2. 提取和恢复数据

基本用法（恢复 DELETE 操作）：

```bash
python binlog_tool_rollback.py extract \
  --binlog-file mysql-bin.000001 \
  --start-position 1234 \
  --stop-position 5678 \
  --database mydb \
  --table mytable \
  --start-datetime "2025-11-17 10:10:57" \
  --stop-datetime "2025-11-17 10:10:58" \
  --output recovery.sql \
  --flashback-mode deletes \
  --direct-parse
```

### 参数说明

| 参数                 | 说明                                               |
| -------------------- | -------------------------------------------------- |
| `--binlog-file`    | binlog 文件路径（必需）                            |
| `--start-position` | 开始位置                                           |
| `--stop-position`  | 结束位置                                           |
| `--start-datetime` | 开始时间（格式: "YYYY-MM-DD HH:MM:SS"）            |
| `--stop-datetime`  | 结束时间（格式: "YYYY-MM-DD HH:MM:SS"）            |
| `--database`       | 数据库名过滤                                       |
| `--table`          | 表名过滤                                           |
| `--output`, `-o` | 输出文件（默认输出到控制台）                       |
| `--flashback-mode` | 闪回模式：deletes/inserts/updates（默认: deletes） |
| `--direct-parse`   | 直接解析模式（避免编码问题）                       |
| `--verbose`        | 输出详细程度(可使用: -v, -vv, -vvv)                |

### 闪回模式说明

* **deletes** : 将 DELETE 操作转换为 INSERT 语句（数据恢复）
* **inserts** : 将 INSERT 操作转换为 DELETE 语句（撤销插入）
* **updates** : 生成反向 UPDATE 语句（撤销更新）

## 使用示例

### 场景1: 误删除数据恢复

1. 首先分析 binlog 找到删除操作的位置：

```bash
python binlog_tool_rollback.py analyze mysql-bin.000001 2025-11-17_10:10:57 2025-11-17_10:10:59
```

2. 查看生成的 `binlog_stats.txt`，找到对应的 DELETE 操作位置
3. 提取并恢复数据：

```bash
python binlog_tool.py extract \
  --binlog-file mysql-bin.000001 \
  --start-position 123456 \
  --stop-position 234567 \
  --database my_database \
  --table my_table \
  --output recovery.sql \
  --flashback-mode deletes
```

4. 检查生成的 SQL 并执行：

```bash
mysql -u username -p < recovery.sql
```

### 场景2: 按时间范围恢复

```bash
python binlog_tool_rollback.py extract \
  --binlog-file mysql-bin.000001 \
  --start-datetime "2025-11-17 10:10:57" \
  --stop-datetime "2025-11-17 10:10:58" \
  --database production_db \
  --output recovery.sql
```

### 场景3: 处理编码问题

如果遇到编码问题，使用直接解析模式：

```bash
python binlog_tool_rollback.py extract \
  --binlog-file mysql-bin.000001 \
  --direct-parse \
  --output recovery.sql
```

## 输出示例

### DML报表示例

```plaintext
binlog              starttime            stoptime             startpos    stoppos     inserts updates deletes database            table   
mysql-bin.000001    2025-11-17_10:10:57  2025-11-17_10:10:58  1234        5678        5       3       2       mydb                users   
mysql-bin.000001    2025-11-17_10:10:58  2025-11-17_10:10:58  5679        6789        0       1       0       mydb                orders  
```

### 恢复 SQL 示例

```sql
-- Binlog数据恢复SQL
-- 生成时间: 2025-11-17 15:30:00
-- 共 2 条SQL语句
-- 请确认SQL正确性后再执行！
-- 建议先备份数据

INSERT INTO `mydb`.`users` VALUES (1, 'John Doe', 'john@example.com');
INSERT INTO `mydb`.`users` VALUES (2, 'Jane Smith', 'jane@example.com');
```

## 注意事项

1. **备份优先** : 执行恢复前务必备份当前数据
2. **权限要求** : 需要读取 binlog 文件的权限和 mysqlbinlog 工具
3. **测试验证** : 在生产环境使用前，先在测试环境验证生成的 SQL
4. **字符编码** : 如遇乱码问题，使用 `--direct-parse` 参数
5. **大文件处理** : 对于大型 binlog 文件，建议指定时间或位置范围

## 故障排除

### 常见问题

1. **mysqlbinlog 命令未找到**
   * 确保 MySQL 客户端工具已安装
   * 将 mysqlbinlog 添加到 PATH 环境变量
2. **编码乱码问题**
   * 使用 `--direct-parse` 参数
   * 检查系统字符编码设置
3. **权限错误**
   * 确保对 binlog 文件有读取权限
   * 使用 sudo 或以正确用户身份运行

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
